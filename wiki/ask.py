"""Interactive wiki Q&A with hybrid search context and optional SSE-style streaming."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from wiki.search import SearchResponse, SearchResult


@dataclass
class AskSource:
    entity: str
    file_path: str
    start_line: int
    wiki_page: str
    relevance_score: float


@dataclass
class AskResponse:
    content: str
    sources: list[AskSource]
    conversation_id: str
    tokens_used: int


@dataclass
class ConversationTurn:
    role: str  # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationHistory:
    conversation_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    repository: str = ""
    scope: str | None = None


@runtime_checkable
class SearchPort(Protocol):
    async def search(
        self,
        repository: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        min_score: float = 0.0,
        *,
        scope: str | None = None,
    ) -> Any: ...


@runtime_checkable
class LLMPort(Protocol):
    async def complete(self, messages: list[dict], **kwargs: Any) -> str: ...


class ConversationStore:
    """In-memory LRU conversation store with TTL eviction."""

    def __init__(self, max_conversations: int = 200, max_turns: int = 10, ttl_seconds: int = 1800) -> None:
        self._max_conversations = max_conversations
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, ConversationHistory] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, conversation_id: str) -> ConversationHistory | None:
        """Get conversation, return None if expired or not found."""
        with self._lock:
            if conversation_id not in self._data:
                return None
            h = self._data[conversation_id]
            now = time.time()
            if now - h.last_active > self._ttl_seconds:
                del self._data[conversation_id]
                return None
            h.last_active = now
            self._data.move_to_end(conversation_id)
            return h

    def save(self, history: ConversationHistory) -> None:
        """Save conversation, evict LRU if over capacity."""
        history.last_active = time.time()
        if len(history.turns) > self._max_turns:
            history.turns = history.turns[-self._max_turns :]
        with self._lock:
            self._data[history.conversation_id] = history
            self._data.move_to_end(history.conversation_id)
            while len(self._data) > self._max_conversations:
                self._data.popitem(last=False)

    def create(self, repository: str, scope: str | None = None) -> ConversationHistory:
        """Create new conversation with UUID."""
        cid = str(uuid.uuid4())
        h = ConversationHistory(conversation_id=cid, repository=repository, scope=scope)
        self.save(h)
        return h


def _format_search_results(resp: SearchResponse) -> str:
    parts: list[str] = []
    for i, r in enumerate(resp.results[:5], 1):
        parts.append(f"### {i}. {r.title} ({r.page_path})\nScore: {r.score:.4f}\nSnippet:\n{r.snippet}\n")
        if r.context:
            parts.append("Context:\n")
            for ck, cv in r.context.items():
                parts.append(f"  - {ck}: {cv}\n")
    return "\n".join(parts).strip()


def _results_to_ask_sources(results: list[SearchResult]) -> list[AskSource]:
    out: list[AskSource] = []
    for r in results[:5]:
        if r.source_locations:
            for loc in r.source_locations:
                ent = str(loc.get("entity") or loc.get("name") or loc.get("fqn") or r.title)
                fpath = str(loc.get("file_path") or loc.get("path") or "")
                line_raw = loc.get("start_line", loc.get("line", 0))
                try:
                    start_line = int(line_raw) if line_raw is not None else 0
                except (TypeError, ValueError):
                    start_line = 0
                out.append(
                    AskSource(
                        entity=ent,
                        file_path=fpath,
                        start_line=start_line,
                        wiki_page=r.page_path,
                        relevance_score=float(r.score),
                    )
                )
        else:
            out.append(
                AskSource(
                    entity=r.title,
                    file_path="",
                    start_line=0,
                    wiki_page=r.page_path,
                    relevance_score=float(r.score),
                )
            )
    return out


def _estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 0)


def _chunk_deltas(text: str) -> list[str]:
    if not text:
        return []
    words = text.split()
    if not words:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    char_budget = 0
    for w in words:
        buf.append(w)
        char_budget += len(w) + 1
        if char_budget >= 24:
            chunks.append(" ".join(buf) + (" " if len(buf) < len(words) else ""))
            buf.clear()
            char_budget = 0
    if buf:
        chunks.append(" ".join(buf))
    return chunks


class WikiAskService:
    def __init__(
        self,
        search: SearchPort,
        llm: LLMPort,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._search = search
        self._llm = llm
        self._store = conversation_store or ConversationStore()

    def _resolve_conversation(
        self,
        repository: str,
        scope: str | None,
        conversation_id: str | None,
    ) -> ConversationHistory:
        if conversation_id:
            existing = self._store.get(conversation_id)
            if existing is not None and existing.repository == repository:
                if scope is not None:
                    existing.scope = scope
                return existing
        return self._store.create(repository, scope)

    def _build_messages(
        self,
        repository: str,
        formatted_results: str,
        prior_turns: list[ConversationTurn],
        question: str,
    ) -> list[dict[str, str]]:
        system_message = f"""You are a code documentation expert. Answer questions about the codebase using the provided context.
Always reference source code locations when available.
Repository: {repository}"""

        context_message = f"""Relevant Wiki pages and code:
{formatted_results}"""

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": context_message},
        ]
        for t in prior_turns:
            messages.append({"role": t.role, "content": t.content})
        messages.append({"role": "user", "content": question})
        return messages

    async def ask_stream(
        self,
        repository: str,
        question: str,
        scope: str | None = None,
        conversation_id: str | None = None,
        mode: str = "hybrid",
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE-style streaming ask."""
        history = self._resolve_conversation(repository, scope, conversation_id)
        prior_turns = list(history.turns)

        search_resp = await self._search.search(
            repository,
            question,
            mode=mode,
            limit=5,
            min_score=0.0,
            scope=scope,
        )
        if not isinstance(search_resp, SearchResponse):
            raise TypeError("search must return SearchResponse")
        formatted = _format_search_results(search_resp)
        sources = _results_to_ask_sources(search_resp.results)
        messages = self._build_messages(repository, formatted, prior_turns, question)

        error_out = (
            "I could not generate an answer because the language model is unavailable. "
            "Please try again later."
        )
        full_text = ""
        try:
            full_text = await self._llm.complete(messages)
        except Exception:
            full_text = error_out

        acc = ""
        for d in _chunk_deltas(full_text):
            acc += d
            yield {"event": "wiki-answer", "data": {"content": acc, "delta": d}}

        yield {"event": "wiki-sources", "data": {"sources": [asdict(s) for s in sources]}}
        tokens_used = _estimate_tokens(full_text)
        yield {
            "event": "wiki-answer-complete",
            "data": {
                "conversation_id": history.conversation_id,
                "tokens_used": tokens_used,
            },
        }

        history.turns.append(ConversationTurn(role="user", content=question))
        history.turns.append(ConversationTurn(role="assistant", content=full_text))
        self._store.save(history)

    async def ask(
        self,
        repository: str,
        question: str,
        scope: str | None = None,
        conversation_id: str | None = None,
        mode: str = "hybrid",
    ) -> AskResponse:
        """Full (non-streaming) ask with source references."""
        content = ""
        sources: list[AskSource] = []
        conv_id = ""
        tokens_used = 0

        async for ev in self.ask_stream(
            repository=repository,
            question=question,
            scope=scope,
            conversation_id=conversation_id,
            mode=mode,
        ):
            et = ev.get("event")
            data = ev.get("data") or {}
            if et == "wiki-answer":
                content = str(data.get("content", ""))
            elif et == "wiki-sources":
                raw = data.get("sources") or []
                sources = [
                    AskSource(
                        entity=str(s.get("entity", "")),
                        file_path=str(s.get("file_path", "")),
                        start_line=int(s.get("start_line", 0) or 0),
                        wiki_page=str(s.get("wiki_page", "")),
                        relevance_score=float(s.get("relevance_score", 0.0)),
                    )
                    for s in raw
                ]
            elif et == "wiki-answer-complete":
                conv_id = str(data.get("conversation_id", ""))
                tokens_used = int(data.get("tokens_used", 0) or 0)

        return AskResponse(
            content=content,
            sources=sources,
            conversation_id=conv_id,
            tokens_used=tokens_used,
        )
