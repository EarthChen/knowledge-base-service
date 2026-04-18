"""Interactive wiki Q&A with hybrid search context and optional SSE-style streaming."""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


def detect_question_type(question: str) -> str:
    """Classify question type by keyword matching (no LLM call).

    Returns one of: 'concept', 'flow', 'relation', 'impact', 'general'

    Priority when multiple cues appear: relation > impact > flow > concept > general.
    """
    if not question or not question.strip():
        return "general"
    q = question.strip()
    lower = q.lower()

    if any(k in q for k in ("关系", "区别", "比较")):
        return "relation"
    if " vs " in f" {lower} " or lower.rstrip(".").endswith(" vs"):
        return "relation"
    if re.search(r"\b(difference|differences|compare|comparison)\b", lower):
        return "relation"

    if any(k in q for k in ("影响", "依赖")):
        return "impact"
    if re.search(r"\b(impact|affect|affects|affected|depends?|dependent|dependency)\b", lower):
        return "impact"

    if any(k in q for k in ("怎么", "流程", "步骤")):
        return "flow"
    if re.search(r"\b(how|process|workflow|steps)\b", lower):
        return "flow"

    if "是什么" in q or "什么是" in q:
        return "concept"
    if re.search(r"\bwhat\s+is\b", lower):
        return "concept"
    if "定义" in q:
        return "concept"
    if re.search(r"\bdescribe\b", lower):
        return "concept"

    return "general"


def _graph_rows(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    data = getattr(result, "data", None)
    if isinstance(data, list):
        return list(data)
    if isinstance(result, list):
        return list(result)
    return []


def _truncate_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if _estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max(max_tokens * 4, 0)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


class GraphEnhancedContextCollector:
    """Collects richer context by traversing the code graph."""

    def __init__(self, graph: GraphPort) -> None:
        self._graph = graph

    @staticmethod
    def _seed_names(search_results: list[SearchResult]) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        for r in search_results[:5]:
            if r.source_locations:
                for loc in r.source_locations:
                    for key in ("entity", "name", "fqn"):
                        raw = loc.get(key)
                        if raw is None:
                            continue
                        s = str(raw).strip()
                        if s and s not in seen:
                            seen.add(s)
                            names.append(s)
            else:
                t = str(r.title).strip()
                if t and t not in seen:
                    seen.add(t)
                    names.append(t)
        return names[:12]

    async def _query_wiki_pages(self, repository: str, paths: list[str]) -> str:
        if not paths:
            return ""
        cypher = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository = $repository AND wp.path IN $paths "
            "RETURN wp.path AS page_path, wp.title AS title, wp.content AS content "
            "ORDER BY wp.path"
        )
        rows = _graph_rows(await self._graph.execute_query(cypher, {"repository": repository, "paths": paths}))
        lines: list[str] = []
        for row in rows:
            title = str(row.get("title") or "")
            pp = str(row.get("page_path") or "")
            body = str(row.get("content") or "")
            lines.append(f"### {title} ({pp})\n{body}")
        return "\n\n".join(lines).strip()

    async def _query_one_hop(self, names: list[str]) -> str:
        if not names:
            return ""
        cypher = (
            "MATCH (n)-[r:CALLS|INHERITS|IMPORTS]-(m) "
            "WHERE n.name IN $names "
            "RETURN type(r) AS rel_type, n.name AS from_name, m.name AS to_name LIMIT 25"
        )
        rows = _graph_rows(await self._graph.execute_query(cypher, {"names": names}))
        lines: list[str] = []
        for row in rows:
            lines.append(f"{row.get('from_name')} -[{row.get('rel_type')}]-> {row.get('to_name')}")
        return "\n".join(lines)

    async def _query_flow_callees(self, names: list[str]) -> str:
        if not names:
            return ""
        cypher = (
            "MATCH (n) WHERE n.name IN $names "
            "MATCH path = (n)-[:CALLS*2..3]->(m) "
            "RETURN [x IN nodes(path) | coalesce(x.name, x.fqn, '')] AS chain LIMIT 15"
        )
        rows = _graph_rows(await self._graph.execute_query(cypher, {"names": names}))
        lines: list[str] = []
        for row in rows:
            chain = row.get("chain") or []
            if isinstance(chain, list):
                lines.append(" -> ".join(str(x) for x in chain if x))
        return "\n".join(lines)

    async def _query_relation_paths(self, names: list[str]) -> str:
        if len(names) < 2:
            return ""
        cypher = (
            "MATCH (seed) WHERE seed.name IN $names AND (seed:Function OR seed:Class OR seed:Module) "
            "WITH collect(DISTINCT seed) AS seeds "
            "WHERE size(seeds) >= 2 "
            "WITH seeds[0] AS seed_a, seeds[-1] AS seed_b "
            "MATCH p = shortestPath((seed_a)-[:CALLS|INHERITS|IMPORTS*1..4]-(seed_b)) "
            "RETURN length(p) AS len, [x IN nodes(p) | coalesce(x.name, x.fqn, '')] AS path LIMIT 5"
        )
        rows = _graph_rows(await self._graph.execute_query(cypher, {"names": names}))
        lines: list[str] = []
        for row in rows:
            path = row.get("path") or []
            if isinstance(path, list):
                lines.append(" -> ".join(str(x) for x in path if x))
        return "\n".join(lines)

    async def _query_impact_callers(self, names: list[str]) -> str:
        if not names:
            return ""
        cypher = (
            "MATCH (n) WHERE n.name IN $names "
            "MATCH path = (caller)-[:CALLS*1..3]->(n) "
            "RETURN DISTINCT caller.name AS caller LIMIT 25"
        )
        rows = _graph_rows(await self._graph.execute_query(cypher, {"names": names}))
        lines: list[str] = []
        for row in rows:
            c = row.get("caller")
            if c:
                lines.append(str(c))
        return "\n".join(lines)

    async def _query_signatures(self, names: list[str]) -> str:
        if not names:
            return ""
        cypher = (
            "MATCH (n) WHERE n.name IN $names AND (n:Function OR n:Class OR n:Method) "
            "RETURN n.name AS name, coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring LIMIT 20"
        )
        rows = _graph_rows(await self._graph.execute_query(cypher, {"names": names}))
        lines: list[str] = []
        for row in rows:
            nm = row.get("name", "")
            sig = row.get("signature", "")
            doc = row.get("docstring", "")
            lines.append(f"{nm}: {sig}\n{doc}".strip())
        return "\n".join(lines)

    async def _query_module_overview(self, repository: str, names: list[str]) -> str:
        if not names:
            return ""
        cypher = (
            "MATCH (m:Module)-[:CONTAINS|DECLARED_IN*0..3]-(n) "
            "WHERE n.name IN $names AND m.repository = $repository "
            "RETURN coalesce(m.name, m.path, '') AS module, "
            "coalesce(m.summary, m.overview, '') AS overview LIMIT 8"
        )
        rows = _graph_rows(await self._graph.execute_query(cypher, {"repository": repository, "names": names}))
        lines: list[str] = []
        for row in rows:
            mod = row.get("module", "")
            ov = row.get("overview") or row.get("summary", "")
            lines.append(f"{mod}: {ov}".strip())
        return "\n".join(lines)

    def _assemble_sections(self, sections: list[tuple[str, str]], token_budget: int) -> str:
        parts: list[str] = []
        remaining = token_budget
        for title, body in sections:
            body = body.strip()
            if not body:
                continue
            header = f"## {title}\n"
            candidate = header + body
            cost = _estimate_tokens(candidate)
            if cost <= remaining:
                parts.append(candidate.rstrip())
                remaining -= cost
                continue
            overhead = _estimate_tokens(header)
            body_budget = max(remaining - overhead, 0)
            truncated_body = _truncate_to_token_budget(body, body_budget)
            if truncated_body:
                parts.append((header + truncated_body).rstrip())
            break
        text = "\n\n".join(parts).strip()
        if _estimate_tokens(text) > token_budget:
            return _truncate_to_token_budget(text, token_budget)
        return text

    async def collect(
        self,
        repository: str,
        search_results: list[SearchResult],
        question_type: str,
        token_budget: int = 8000,
    ) -> str:
        """Build enriched context string within token budget.

        Collection priority:
        1. Full Wiki page content for top results
        2. Call chain context (callers/callees, 1-3 hops based on question_type)
        3. Entity code signatures (docstring, parameters, return type)
        4. Module architecture context (module overview summary)

        All context sorted by relevance, truncated at token_budget.
        """
        paths = [r.page_path for r in search_results[:5]]
        names = self._seed_names(search_results)

        wiki_text = await self._query_wiki_pages(repository, paths)

        graph_section = ""
        if question_type in ("concept", "general"):
            graph_section = await self._query_one_hop(names)
        elif question_type == "flow":
            graph_section = await self._query_flow_callees(names)
        elif question_type == "relation":
            graph_section = await self._query_relation_paths(names)
        elif question_type == "impact":
            graph_section = await self._query_impact_callers(names)

        sig_text = await self._query_signatures(names)
        mod_text = await self._query_module_overview(repository, names)

        sections: list[tuple[str, str]] = [
            ("Full wiki pages", wiki_text),
            ("Graph context", graph_section),
            ("Entity signatures", sig_text),
            ("Module architecture", mod_text),
        ]
        return self._assemble_sections(sections, token_budget)


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
        graph: GraphPort | None = None,
    ) -> None:
        self._search = search
        self._llm = llm
        self._store = conversation_store or ConversationStore()
        self._graph = graph

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
        system_message = (
            "You are a code documentation expert. Answer questions about the codebase "
            "using the provided context.\n"
            "Always reference source code locations when available.\n"
            f"Repository: {repository}"
        )

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
        if self._graph is not None:
            collector = GraphEnhancedContextCollector(self._graph)
            qtype = detect_question_type(question)
            enriched = await collector.collect(
                repository,
                search_resp.results,
                qtype,
                token_budget=8000,
            )
            if enriched.strip():
                formatted = enriched
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
