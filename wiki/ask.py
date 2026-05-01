"""Interactive wiki Q&A with hybrid search context and optional SSE-style streaming."""

from __future__ import annotations

import inspect
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from log import get_logger
from store.conversation_store import SqliteConversationStore
from store.wiki_store import WikiStore
from wiki.crystallizer import crystallize as crystallize_wiki_page
from wiki.llm_port import LLMPort
from wiki.reasoning_path import (
    ReasoningPath,
    ReasoningStage,
    extract_entities_in_answer,
)
from wiki.search import SearchResponse, SearchResult

if TYPE_CHECKING:
    from wiki.token_budget import TokenBudgetResolver

log = get_logger(__name__)


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
    reasoning_path: dict[str, Any] | None = None


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
class GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


@runtime_checkable
class MemoryLoopPort(Protocol):
    """Optional wiki Q&A memory (R-Phase 8)."""

    async def record(
        self,
        question: str,
        answer: str,
        source_pages: list[str],
        *,
        business_id: str | None = None,
    ) -> str: ...


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


_WIKI_TYPE_TOKEN_BUDGET: dict[str, int] = {
    "concept": 6000,
    "flow": 10000,
    "relation": 10000,
    "impact": 8000,
    "general": 8000,
}

_default_resolver: TokenBudgetResolver | None = None


def set_default_resolver(resolver: TokenBudgetResolver) -> None:
    global _default_resolver
    _default_resolver = resolver


def wiki_context_token_budget_from_resolver(
    question: str,
    question_type: str | None,
    resolver: TokenBudgetResolver,
) -> int:
    qt = question_type if question_type is not None else detect_question_type(question)
    base = resolver.ask_budget(qt)
    q_tokens = max(len(question) // 4, 0)
    return min(base + q_tokens, resolver.budget("decomposition"))


def wiki_context_token_budget(question: str, question_type: str | None = None) -> int:
    """Token budget for graph-enhanced wiki context collection.

    Combines a base allowance per ``question_type`` with the estimated token count of
    ``question`` (complexity). Capped to avoid runaway prompts.
    """
    if _default_resolver is not None:
        return wiki_context_token_budget_from_resolver(
            question, question_type, _default_resolver
        )
    qt = question_type if question_type is not None else detect_question_type(question)
    base = _WIKI_TYPE_TOKEN_BUDGET.get(qt, 8000)
    q_tokens = max(len(question) // 4, 0)
    return min(base + q_tokens, 16000)


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

    def __init__(self, wiki_store: WikiStore) -> None:
        self._wiki = wiki_store

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
        rows = _graph_rows(await self._wiki.ask_query_wiki_pages(repository, paths))
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
        rows = _graph_rows(await self._wiki.ask_query_one_hop(names))
        lines: list[str] = []
        for row in rows:
            lines.append(f"{row.get('from_name')} -[{row.get('rel_type')}]-> {row.get('to_name')}")
        return "\n".join(lines)

    async def _query_flow_callees(self, names: list[str]) -> str:
        if not names:
            return ""
        rows = _graph_rows(await self._wiki.ask_query_flow_callees(names))
        lines: list[str] = []
        for row in rows:
            chain = row.get("chain") or []
            if isinstance(chain, list):
                lines.append(" -> ".join(str(x) for x in chain if x))
        return "\n".join(lines)

    async def _query_relation_paths(self, names: list[str]) -> str:
        if len(names) < 2:
            return ""
        rows = _graph_rows(await self._wiki.ask_query_relation_paths(names))
        lines: list[str] = []
        for row in rows:
            path = row.get("path") or []
            if isinstance(path, list):
                lines.append(" -> ".join(str(x) for x in path if x))
        return "\n".join(lines)

    async def _query_repo_scoped_shortest_path(self, repository: str, names: list[str]) -> str:
        """Supplement relation questions with a repository-scoped path (see GraphQueryRepository)."""
        if len(names) < 2:
            return ""
        a, b = names[0], names[1]
        if a == b:
            for n in names[2:]:
                if n != a:
                    b = n
                    break
            else:
                return ""
        raw = await self._wiki.ask_query_shortest_path_between(repository, a, b)
        if not raw.get("ok"):
            return ""
        rows = raw.get("rows") or []
        lines: list[str] = []
        for row in rows:
            depth = row.get("depth")
            node_list = row.get("nodes") or []
            rel_list = row.get("rels") or []
            seg = " -> ".join(str(x) for x in node_list if str(x).strip())
            rel_str = ", ".join(str(x) for x in rel_list) if rel_list else ""
            suffix = f" | edges: {rel_str}" if rel_str else ""
            lines.append(f"Repository-scoped shortest path (depth {depth}): {seg}{suffix}")
        return "\n".join(lines)

    async def _query_impact_callers(self, names: list[str]) -> str:
        if not names:
            return ""
        rows = _graph_rows(await self._wiki.ask_query_impact_callers(names))
        lines: list[str] = []
        for row in rows:
            c = row.get("caller")
            if c:
                lines.append(str(c))
        return "\n".join(lines)

    async def _query_signatures(self, names: list[str]) -> str:
        if not names:
            return ""
        rows = _graph_rows(await self._wiki.ask_query_signatures(names))
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
        rows = _graph_rows(await self._wiki.ask_query_module_overview(repository, names))
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
            scoped = await self._query_repo_scoped_shortest_path(repository, names)
            if scoped:
                graph_section = (
                    f"{graph_section}\n{scoped}".strip() if graph_section else scoped
                )
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


def _chunks_to_ask_sources(chunks: list[Any]) -> list[AskSource]:
    """Map RAG :class:`~wiki.rag.protocol.Chunk` list to citation rows for SSE."""
    out: list[AskSource] = []
    for c in chunks[:20]:
        meta: dict[str, Any] = {}
        raw_meta = getattr(c, "metadata", None)
        if isinstance(raw_meta, dict):
            meta = raw_meta
        title = str(getattr(c, "title", "") or "")
        page = str(meta.get("page_path") or title)
        fpath = str(meta.get("file_path") or "")
        ent = title or page
        try:
            start_line = int(meta.get("start_line", 0) or 0)
        except (TypeError, ValueError):
            start_line = 0
        try:
            rel = float(getattr(c, "relevance", 0.0) or 0.0)
        except (TypeError, ValueError):
            rel = 0.0
        out.append(
            AskSource(
                entity=ent,
                file_path=fpath,
                start_line=start_line,
                wiki_page=page,
                relevance_score=rel,
            )
        )
    return out


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


def _search_entity_hits_for_reasoning(results: list[SearchResult], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for r in results[:limit]:
        t = str(r.title).strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
        for loc in r.source_locations or []:
            for key in ("entity", "name", "fqn"):
                raw = loc.get(key)
                if raw is None:
                    continue
                s = str(raw).strip()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def _retriever_label_for_search_mode(mode: str) -> str:
    if mode == "semantic":
        return "vector"
    if mode == "graph":
        return "graph"
    if mode == "keyword":
        return "fts"
    if mode == "hybrid":
        return "wiki_search"
    return "wiki_search"


def _graph_reasoning_stages_for_qtype(
    question_type: str, search_results: list[SearchResult]
) -> list[ReasoningStage]:
    names = GraphEnhancedContextCollector._seed_names(search_results)
    if not names:
        return []
    n = list(names)
    if question_type in ("concept", "general"):
        return [ReasoningStage("graph_context", "graph", n, metadata={"kind": "one_hop"})]
    if question_type == "flow":
        return [ReasoningStage("graph_context", "graph", n, metadata={"kind": "flow_callees"})]
    if question_type == "relation":
        stages = [ReasoningStage("graph_context", "graph", n, metadata={"kind": "relation_paths"})]
        if len(n) >= 2:
            stages.append(
                ReasoningStage(
                    "graph_path",
                    "graph_path",
                    n[:2],
                    metadata={"kind": "shortest_path"},
                )
            )
        return stages
    if question_type == "impact":
        return [ReasoningStage("graph_context", "graph", n, metadata={"kind": "impact_callers"})]
    return []


def _build_wiki_ask_reasoning_path(
    search_resp: SearchResponse,
    search_mode: str,
    question_type: str,
    answer_text: str,
    *,
    include_graph_stages: bool,
) -> ReasoningPath:
    """Provenance: search hit entities + graph stages the collector would run (if wiki store used)."""
    search_hits = _search_entity_hits_for_reasoning(search_resp.results)
    top_score = search_resp.results[0].score if search_resp.results else None
    stages: list[ReasoningStage] = [
        ReasoningStage(
            stage_name="search",
            retriever=_retriever_label_for_search_mode(search_mode),
            entity_hits=search_hits,
            score=top_score,
            metadata={"mode": search_mode, "query_expansion": search_resp.query_expansion},
        )
    ]
    if include_graph_stages:
        stages.extend(_graph_reasoning_stages_for_qtype(question_type, list(search_resp.results)))
    seed = GraphEnhancedContextCollector._seed_names(search_resp.results)
    candidates: list[str] = []
    seen_c: set[str] = set()
    for x in search_hits + seed:
        if x not in seen_c:
            seen_c.add(x)
            candidates.append(x)
    return ReasoningPath(
        stages=stages,
        answer_entities=extract_entities_in_answer(answer_text, candidates),
    )


def _estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 0)


def _is_async_text_stream_method(fn: object) -> bool:
    """True if ``fn`` is an async generator (streaming text), not a sync mock."""
    if fn is None or not callable(fn):
        return False
    unwrapped = inspect.unwrap(fn)  # type: ignore[unreachable]
    f = unwrapped
    if inspect.ismethod(f):
        f = f.__func__
    return inspect.isasyncgenfunction(f)


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
        search: SearchPort | None = None,
        llm: LLMPort | None = None,
        rag_engine: Any = None,
        conversation_store: ConversationStore | SqliteConversationStore | None = None,
        graph: GraphPort | None = None,
        wiki_store: WikiStore | None = None,
        memory_loop: MemoryLoopPort | None = None,
    ) -> None:
        self._store: ConversationStore | SqliteConversationStore = conversation_store or ConversationStore()
        self._wiki_store = wiki_store or (WikiStore(graph) if graph is not None else None)
        self._memory_loop = memory_loop
        self._rag_engine = rag_engine

    async def _resolve_conversation(
        self,
        repository: str,
        scope: str | None,
        conversation_id: str | None,
    ) -> ConversationHistory:
        if conversation_id:
            result = self._store.get(conversation_id)
            if inspect.isawaitable(result):
                result = await result
            existing = result
            if existing is not None and existing.repository == repository:
                if scope is not None:
                    existing.scope = scope
                return existing
        result = self._store.create(repository, scope)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def ask_stream(
        self,
        repository: str,
        question: str,
        scope: str | None = None,
        conversation_id: str | None = None,
        mode: str = "hybrid",
        *,
        record_memory: bool = False,
        business_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE-style streaming ask.

        If ``record_memory`` is true and ``business_id`` is set, persists Q&A via memory loop
        (when configured).
        """
        from wiki.rag.protocol import RetrievalScope

        history = await self._resolve_conversation(repository, scope, conversation_id)

        scope_obj = RetrievalScope(
            scope_type="business" if business_id else "global",
            business_id=business_id,
            repository=repository,
            page_path=scope,
        )

        error_out = (
            "I could not generate an answer because the language model is unavailable. "
            "Please try again later."
        )
        full_text = ""
        rag_state: dict[str, Any] = {}
        try:
            rag_state = await self._rag_engine.arun(
                question=question,
                scope=scope_obj,
                max_rounds=5,
            )
            full_text = str(rag_state.get("current_draft", ""))
        except Exception:
            log.warning("wiki_ask_rag_failed", repository=repository, exc_info=True)
            full_text = error_out

        chunks_raw = rag_state.get("accumulated_context") if rag_state else None
        chunks_list: list[Any] = list(chunks_raw) if isinstance(chunks_raw, list) else []
        sources = _chunks_to_ask_sources(chunks_list)

        if rag_state:
            for sse_ev in rag_state.get("sse_events", []):
                yield {"event": "rag-progress", "data": sse_ev}

        acc = ""
        for d in _chunk_deltas(full_text):
            acc += d
            yield {"event": "wiki-answer", "data": {"content": acc, "delta": d}}

        yield {"event": "wiki-sources", "data": {"sources": [asdict(s) for s in sources]}}
        tokens_used = _estimate_tokens(full_text)
        complete_data: dict[str, Any] = {
            "conversation_id": history.conversation_id,
            "tokens_used": tokens_used,
            "iterative_rag": True,
            "confidence": float(rag_state.get("confidence", 0.0)) if rag_state else 0.0,
            "total_rounds": int(rag_state.get("round", 1)) if rag_state else 1,
        }
        yield {"event": "wiki-answer-complete", "data": complete_data}

        history.turns.append(ConversationTurn(role="user", content=question))
        history.turns.append(ConversationTurn(role="assistant", content=full_text))
        save_result = self._store.save(history)
        if inspect.isawaitable(save_result):
            await save_result

        if (
            record_memory
            and business_id
            and self._memory_loop is not None
            and full_text
            and full_text != error_out
        ):
            try:
                pgs = [s.wiki_page for s in sources if s.wiki_page]
                await self._memory_loop.record(
                    question, full_text, pgs, business_id=business_id,
                )
            except Exception:
                log.warning("memory_loop_record_failed", exc_info=True)

    async def ask(
        self,
        repository: str,
        question: str,
        scope: str | None = None,
        conversation_id: str | None = None,
        mode: str = "hybrid",
        *,
        record_memory: bool = False,
        business_id: str | None = None,
    ) -> AskResponse:
        """Full (non-streaming) ask with source references."""
        content = ""
        sources: list[AskSource] = []
        conv_id = ""
        tokens_used = 0
        reasoning_path: dict[str, Any] | None = None

        async for ev in self.ask_stream(
            repository=repository,
            question=question,
            scope=scope,
            conversation_id=conversation_id,
            mode=mode,
            record_memory=record_memory,
            business_id=business_id,
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
                rp = data.get("reasoning_path")
                reasoning_path = rp if isinstance(rp, dict) else None

        return AskResponse(
            content=content,
            sources=sources,
            conversation_id=conv_id,
            tokens_used=tokens_used,
            reasoning_path=reasoning_path,
        )

    async def crystallize(
        self,
        repository: str,
        question: str,
        answer: str,
        sources: list[str],
        business_id: str,
    ) -> dict[str, str]:
        """Save a Q&A pair as a new wiki page with backlinks to source paths."""
        if self._wiki_store is None:
            msg = "Wiki graph store is not configured"
            raise RuntimeError(msg)
        return await crystallize_wiki_page(
            self._wiki_store,
            repository,
            question,
            answer,
            sources,
            business_id,
        )
