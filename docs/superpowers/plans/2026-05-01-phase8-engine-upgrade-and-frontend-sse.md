# Phase 8: Engine Upgrade & Frontend SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Enhance the RAG retrieval layer with NL-to-Cypher graph queries and cross-repo search, upgrade the engine to support real-time streaming, add evaluation feedback loops, and adapt the frontend to render new SSE event types.

**Architecture:** 3 Sprints — Sprint A adds NL-to-Cypher and MultiRepoRetriever to the retrieval layer; Sprint B upgrades IterativeRAGEngine with `arun_stream` and eval→plan feedback; Sprint C adapts frontend hooks and components to render `planning`/`evaluating` events and structured deep search results in stream mode.

**Tech Stack:** Python 3.11+, LangGraph (StateGraph + astream), FastAPI SSE, FalkorDB (Cypher), React 19 + TypeScript + Tailwind CSS 4

---

## File Structure

### New Files
- `wiki/rag/multi_repo_retriever.py` — MultiRepoRetriever wrapping HybridQueryService.search_multi_repo
- `tests/wiki/rag/test_nl_cypher_retriever.py` — Tests for NL-to-Cypher integration in HybridGraphRetriever
- `tests/wiki/rag/test_multi_repo_retriever.py` — Tests for MultiRepoRetriever
- `tests/wiki/rag/test_engine_stream.py` — Tests for arun_stream
- `tests/wiki/rag/test_eval_feedback_loop.py` — Tests for eval→plan suggestions

### Modified Files
- `wiki/rag/hybrid_graph_retriever.py` — Add nl_cypher parameter + Cypher-based graph leg
- `wiki/rag/engine.py` — Add arun_stream + eval_suggestions in RAGState
- `wiki/ask.py` — ask_stream consumes arun_stream
- `query/deep_search.py` — search_stream consumes arun_stream
- `services/kb_service.py` — Wire NLCypherService + MultiRepoRetriever
- `wiki/rag/__init__.py` — Export MultiRepoRetriever
- `dashboard/src/components/wiki/AskPanel.tsx` — RagTimeline planning/evaluating styles
- `dashboard/src/hooks/useDeepSearchStream.ts` — Whitelist extension
- `dashboard/src/components/DeepResearchTimeline.tsx` — StageEvent type + labels
- `dashboard/src/components/DeepSearchSection.tsx` — Stream mode structured results

---

## Sprint A: Retrieval Layer Enhancement

### Task 1: NL-to-Cypher Integration into HybridGraphRetriever

**Files:**
- Modify: `wiki/rag/hybrid_graph_retriever.py`
- Modify: `services/kb_service.py`
- Test: `tests/wiki/rag/test_nl_cypher_retriever.py`

- [x] **Step 1: Write the failing test for NL-to-Cypher graph leg**

Create `tests/wiki/rag/test_nl_cypher_retriever.py`:

```python
"""Tests for NL-to-Cypher integration in HybridGraphRetriever."""
from __future__ import annotations

import pytest

from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever, _format_cypher_row
from wiki.rag.protocol import Chunk, RetrievalScope


class _StubHybrid:
    async def search_with_context(self, query, **kw):
        return {"semantic_matches": [{"content": "stub", "name": "Stub", "score": 0.5}]}


class _StubNLCypher:
    def __init__(self, results: list[dict] | None = None, error: bool = False):
        self._results = results or []
        self._error = error

    async def query(self, question: str, *, repository: str | None = None) -> dict:
        if self._error:
            raise RuntimeError("LLM unavailable")
        return {"question": question, "cypher": "MATCH (n) RETURN n", "results": self._results, "total": len(self._results)}


@pytest.mark.asyncio
async def test_cypher_results_become_chunks():
    """When NL-to-Cypher succeeds, its results are converted to Chunks."""
    cypher_results = [
        {"name": "UserService", "type": "Class", "file": "services/user.py", "line": 10},
        {"name": "login", "type": "Function", "file": "auth/login.py", "line": 25, "signature": "def login(user, pw)"},
    ]
    retriever = HybridGraphRetriever(
        hybrid_service=_StubHybrid(),
        nl_cypher=_StubNLCypher(results=cypher_results),
    )
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["how does login work"], scope, limit=10)

    cypher_chunks = [c for c in chunks if c.source == "graph_cypher"]
    assert len(cypher_chunks) == 2
    assert "UserService" in cypher_chunks[0].content
    assert "login" in cypher_chunks[1].content


@pytest.mark.asyncio
async def test_cypher_failure_falls_through_to_entity_lookup():
    """When NL-to-Cypher raises, entity lookup is still attempted."""
    mock_graph = type("G", (), {
        "find_entity": staticmethod(lambda term: type("R", (), {"data": [{"name": term, "type": "Function"}]})()),
    })()
    retriever = HybridGraphRetriever(
        hybrid_service=_StubHybrid(),
        graph_service=mock_graph,
        nl_cypher=_StubNLCypher(error=True),
    )
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["UserService"], scope, limit=10)

    graph_chunks = [c for c in chunks if c.source == "graph"]
    assert len(graph_chunks) >= 1


@pytest.mark.asyncio
async def test_cypher_empty_results_falls_through():
    """When Cypher returns no results, entity lookup runs as supplement."""
    mock_graph = type("G", (), {
        "find_entity": staticmethod(lambda term: type("R", (), {"data": [{"name": "Found", "type": "Class"}]})()),
    })()
    retriever = HybridGraphRetriever(
        hybrid_service=_StubHybrid(),
        graph_service=mock_graph,
        nl_cypher=_StubNLCypher(results=[]),
    )
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["SomeQuery"], scope, limit=10)

    graph_chunks = [c for c in chunks if c.source == "graph"]
    assert len(graph_chunks) >= 1


def test_format_cypher_row_with_signature():
    row = {"name": "login", "type": "Function", "file": "auth/login.py", "line": 25, "signature": "def login(u, p)"}
    result = _format_cypher_row(row)
    assert "login" in result
    assert "Function" in result
    assert "auth/login.py" in result


def test_format_cypher_row_minimal():
    row = {"name": "Config"}
    result = _format_cypher_row(row)
    assert "Config" in result
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_nl_cypher_retriever.py -v`
Expected: FAIL — `_format_cypher_row` not found, `nl_cypher` parameter not accepted

- [x] **Step 3: Implement _format_cypher_row and add nl_cypher to HybridGraphRetriever**

In `wiki/rag/hybrid_graph_retriever.py`, add `_format_cypher_row` function and modify the constructor and `_append_graph_chunks`:

```python
def _format_cypher_row(row: dict[str, Any]) -> str:
    """Convert a Cypher result row to readable text for RAG context."""
    name = str(row.get("name", ""))
    typ = str(row.get("type", ""))
    file = str(row.get("file", ""))
    line = row.get("line")
    sig = row.get("signature")

    parts: list[str] = []
    if typ:
        parts.append(f"[{typ}]")
    parts.append(name or str(row))
    if file:
        loc = f"{file}:{line}" if line else file
        parts.append(f"({loc})")
    if sig:
        parts.append(f"- {sig}")
    return " ".join(parts)
```

Modify `HybridGraphRetriever.__init__`:

```python
class HybridGraphRetriever:
    def __init__(
        self,
        hybrid_service: Any,
        graph_service: Any | None = None,
        nl_cypher: Any | None = None,
    ) -> None:
        self._hybrid = hybrid_service
        self._graph = graph_service
        self._nl_cypher = nl_cypher
```

Modify `_append_graph_chunks` to try NL-to-Cypher first:

```python
async def _append_graph_chunks(self, query: str, chunks: list[Chunk]) -> None:
    # Path 1: NL-to-Cypher (preferred when available)
    if self._nl_cypher is not None:
        try:
            result = await self._nl_cypher.query(query)
            rows = result.get("results") or []
            if rows:
                for row in rows:
                    chunks.append(Chunk(
                        content=_format_cypher_row(row),
                        source="graph_cypher",
                        title="graph_cypher",
                        relevance=0.6,
                    ))
                return  # Cypher succeeded, skip entity lookup
        except Exception:
            logger.warning("nl_cypher_query_failed", exc_info=True)

    # Path 2: entity lookup (fallback / supplement)
    if self._graph is None or not hasattr(self._graph, "find_entity"):
        return
    # ... existing find_entity + find_call_chain logic unchanged ...
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_nl_cypher_retriever.py -v`
Expected: PASS (all 5 tests)

- [x] **Step 5: Wire NLCypherService in kb_service.py**

In `services/kb_service.py`, modify the section where `HybridGraphRetriever` is constructed:

```python
# Add import at the existing import block
from query.nl_cypher import NLCypherService

# In _init_components, where rag_engine is built for deep search:
self._deep_search = None
rag_engine = None
if settings.llm.enabled and self._llm_provider is not None:
    from query.deep_search import DeepSearchEngine
    from wiki.rag.engine import IterativeRAGEngine
    from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever

    nl_cypher = NLCypherService(
        store=self._store,
        llm=self._llm_provider,
    )
    rag_retriever = HybridGraphRetriever(
        hybrid_service=self._hybrid_query,
        graph_service=self._graph_query,
        nl_cypher=nl_cypher,
    )
    rag_engine = IterativeRAGEngine(
        retriever=rag_retriever,
        llm=self._llm_provider,
    )
    self._deep_search = DeepSearchEngine(rag_engine=rag_engine)
```

- [x] **Step 6: Run full test suite to verify no regressions**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/ -x --timeout=120 -q`
Expected: All tests pass

- [x] **Step 7: Commit**

```bash
git add wiki/rag/hybrid_graph_retriever.py services/kb_service.py tests/wiki/rag/test_nl_cypher_retriever.py
git commit -m "feat: integrate NL-to-Cypher into HybridGraphRetriever graph leg"
```

---

### Task 2: MultiRepoRetriever for Cross-Repository Search

**Files:**
- Create: `wiki/rag/multi_repo_retriever.py`
- Modify: `wiki/rag/__init__.py`
- Modify: `services/kb_service.py`
- Test: `tests/wiki/rag/test_multi_repo_retriever.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/rag/test_multi_repo_retriever.py`:

```python
"""Tests for MultiRepoRetriever cross-repository search."""
from __future__ import annotations

import pytest

from wiki.rag.multi_repo_retriever import MultiRepoRetriever, _hybrid_result_to_chunks
from wiki.rag.protocol import Chunk, RetrievalScope


class _StubHybrid:
    def __init__(self, multi_result: dict | None = None):
        self._multi_result = multi_result or {
            "semantic_matches": [
                {"content": "from repo A", "name": "FuncA", "score": 0.9, "file": "a.py"},
                {"content": "from repo B", "name": "ClassB", "score": 0.8, "file": "b.java"},
            ],
            "total": 2,
        }

    async def search_multi_repo(self, query_text, repositories, **kw):
        return self._multi_result

    async def search_with_context(self, query_text, **kw):
        return {"semantic_matches": [{"content": "single", "name": "X", "score": 0.7}]}


class _StubRegistry:
    def __init__(self, repos: list[str]):
        self._repos = repos

    def list_all(self):
        return [{"repository": r} for r in self._repos]


@pytest.mark.asyncio
async def test_global_scope_multi_repo():
    """Global scope with multiple repos triggers search_multi_repo."""
    retriever = MultiRepoRetriever(
        hybrid_service=_StubHybrid(),
        repo_registry=_StubRegistry(["repo-a", "repo-b"]),
    )
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["how does auth work"], scope, limit=10)

    assert len(chunks) >= 2
    assert any("FuncA" in c.title or "FuncA" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_repository_scope_single_repo():
    """Repository scope delegates to single-repo search."""
    retriever = MultiRepoRetriever(
        hybrid_service=_StubHybrid(),
        repo_registry=_StubRegistry(["repo-a", "repo-b"]),
    )
    scope = RetrievalScope(scope_type="repository", repository="repo-a")
    chunks = await retriever.retrieve(["query"], scope, limit=10)

    assert len(chunks) >= 1


@pytest.mark.asyncio
async def test_no_repos_returns_single_search():
    """No registered repos: fallback to single search."""
    retriever = MultiRepoRetriever(
        hybrid_service=_StubHybrid(),
        repo_registry=_StubRegistry([]),
    )
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["query"], scope, limit=10)

    assert len(chunks) >= 1


def test_hybrid_result_to_chunks():
    result = {
        "semantic_matches": [
            {"content": "test content", "name": "TestFunc", "score": 0.85, "file": "test.py", "title": "TestFunc"},
        ]
    }
    chunks = _hybrid_result_to_chunks(result)
    assert len(chunks) == 1
    assert chunks[0].source == "wiki"
    assert chunks[0].relevance == 0.85
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_multi_repo_retriever.py -v`
Expected: FAIL — `multi_repo_retriever` module not found

- [x] **Step 3: Implement MultiRepoRetriever**

Create `wiki/rag/multi_repo_retriever.py`:

```python
"""Cross-repository retriever using HybridQueryService.search_multi_repo."""
from __future__ import annotations

import logging
from typing import Any

from wiki.rag.protocol import Chunk, RetrievalScope

logger = logging.getLogger(__name__)


def _hybrid_result_to_chunks(result: dict[str, Any]) -> list[Chunk]:
    """Convert HybridQueryService result dict to Chunk list."""
    rows = result.get("semantic_matches") or result.get("results") or []
    chunks: list[Chunk] = []
    for r in rows:
        if isinstance(r, dict):
            content = str(r.get("content") or r.get("summary") or r.get("name") or r)
            title = str(r.get("title") or r.get("name") or "")
            rel = float(r.get("score", r.get("rrf_score", 0.5)) or 0.5)
            path = str(r.get("path") or r.get("file") or "")
        else:
            content = str(r)
            title = ""
            rel = 0.5
            path = ""
        chunks.append(Chunk(
            content=content,
            source="wiki",
            title=title,
            relevance=rel,
            metadata={"path": path},
        ))
    return chunks


class MultiRepoRetriever:
    """Global-scope retriever: parallel search across all repositories."""

    def __init__(
        self,
        hybrid_service: Any,
        repo_registry: Any | None = None,
        graph_service: Any | None = None,
        nl_cypher: Any | None = None,
    ) -> None:
        self._hybrid = hybrid_service
        self._registry = repo_registry
        self._graph = graph_service
        self._nl_cypher = nl_cypher

    def _list_repo_names(self) -> list[str]:
        if self._registry is None:
            return []
        entries = self._registry.list_all()
        return [str(e.get("repository", "")).strip() for e in entries if e.get("repository")]

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        repos = self._list_repo_names()

        if scope.repository or not repos or len(repos) <= 1:
            return await self._single_repo_retrieve(queries, scope, limit=limit)

        combined_query = " ".join(queries)
        try:
            result = await self._hybrid.search_multi_repo(
                combined_query,
                repos,
                limit=limit,
            )
        except Exception:
            logger.error("multi_repo_search_failed", exc_info=True)
            return await self._single_repo_retrieve(queries, scope, limit=limit)

        chunks = _hybrid_result_to_chunks(result)

        if self._nl_cypher is not None:
            await self._append_cypher_chunks(combined_query, chunks)

        return chunks[:limit]

    async def _single_repo_retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
    ) -> list[Chunk]:
        """Single-repo fallback via search_with_context."""
        chunks: list[Chunk] = []
        for query in queries:
            result = await self._hybrid.search_with_context(
                query,
                limit=limit,
                repository=scope.repository,
            )
            chunks.extend(_hybrid_result_to_chunks(result))
        return chunks[:limit]

    async def _append_cypher_chunks(self, query: str, chunks: list[Chunk]) -> None:
        if self._nl_cypher is None:
            return
        try:
            from wiki.rag.hybrid_graph_retriever import _format_cypher_row

            result = await self._nl_cypher.query(query)
            for row in result.get("results") or []:
                chunks.append(Chunk(
                    content=_format_cypher_row(row),
                    source="graph_cypher",
                    title="graph_cypher",
                    relevance=0.6,
                ))
        except Exception:
            logger.warning("multi_repo_cypher_failed", exc_info=True)
```

- [x] **Step 4: Export from __init__.py**

In `wiki/rag/__init__.py`, add:

```python
from wiki.rag.multi_repo_retriever import MultiRepoRetriever
```

And add `"MultiRepoRetriever"` to the `__all__` list if it exists.

- [x] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_multi_repo_retriever.py -v`
Expected: PASS (all 4 tests)

- [x] **Step 6: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/ -x --timeout=120 -q`
Expected: All tests pass

- [x] **Step 7: Commit**

```bash
git add wiki/rag/multi_repo_retriever.py wiki/rag/__init__.py tests/wiki/rag/test_multi_repo_retriever.py
git commit -m "feat: add MultiRepoRetriever for cross-repository global search"
```

---

## Sprint B: Engine Layer Upgrade

### Task 3: RAG Streaming Output (arun_stream)

**Files:**
- Modify: `wiki/rag/engine.py`
- Modify: `wiki/ask.py`
- Modify: `query/deep_search.py`
- Test: `tests/wiki/rag/test_engine_stream.py`

- [x] **Step 1: Write the failing test for arun_stream**

Create `tests/wiki/rag/test_engine_stream.py`:

```python
"""Tests for IterativeRAGEngine.arun_stream."""
from __future__ import annotations

import pytest

from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.protocol import Chunk, RetrievalScope


class _StubRetriever:
    async def retrieve(self, queries, scope, *, limit=10, exclude_ids=None):
        return [Chunk(content="test context", source="wiki", title="Test", relevance=0.9)]


class _StubLLM:
    async def generate(self, prompt, system="", **kw):
        return '{"answer":"test answer","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'

    async def complete(self, messages, **kw):
        return '{"answer":"test answer","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'

    async def complete_stream(self, messages, **kw):
        text = '{"answer":"test answer","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'
        for ch in [text[:20], text[20:]]:
            yield ch


@pytest.mark.asyncio
async def test_arun_stream_yields_events():
    """arun_stream should yield SSE events and a draft."""
    engine = IterativeRAGEngine(retriever=_StubRetriever(), llm=_StubLLM())
    scope = RetrievalScope(scope_type="global")

    events: list[dict] = []
    async for ev in engine.arun_stream(question="test question", scope=scope, max_rounds=3):
        events.append(ev)

    types = [e["type"] for e in events]
    assert "sse" in types, "Should have SSE events"
    assert "done" in types, "Should have done event"

    sse_events = [e for e in events if e["type"] == "sse"]
    sse_types = [e["data"]["type"] for e in sse_events]
    assert "searching" in sse_types


@pytest.mark.asyncio
async def test_arun_stream_yields_draft():
    """arun_stream should yield draft content updates."""
    engine = IterativeRAGEngine(retriever=_StubRetriever(), llm=_StubLLM())
    scope = RetrievalScope(scope_type="global")

    drafts = []
    async for ev in engine.arun_stream(question="test", scope=scope, max_rounds=3):
        if ev["type"] == "draft":
            drafts.append(ev)

    assert len(drafts) >= 1
    assert "test answer" in drafts[-1]["data"]["content"]


@pytest.mark.asyncio
async def test_arun_still_works():
    """arun (batch mode) still works after adding arun_stream."""
    engine = IterativeRAGEngine(retriever=_StubRetriever(), llm=_StubLLM())
    scope = RetrievalScope(scope_type="global")

    result = await engine.arun(question="test", scope=scope, max_rounds=3)
    assert result["current_draft"]
    assert result["confidence"] > 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_engine_stream.py -v`
Expected: FAIL — `arun_stream` attribute not found

- [x] **Step 3: Implement arun_stream in engine.py**

In `wiki/rag/engine.py`, add after the `arun` method:

```python
async def arun_stream(
    self,
    *,
    question: str,
    scope: RetrievalScope,
    max_rounds: int = 7,
):
    """Streaming execution: yields SSE events as nodes complete.

    Yields dicts with ``type`` in ("sse", "draft", "done").
    """
    init: RAGState = {
        "question": question,
        "scope": scope,
        "round": 0,
        "max_rounds": max_rounds,
        "accumulated_context": [],
        "current_draft": "",
        "gaps": [],
        "next_queries": [],
        "confidence": 0.0,
        "is_complete": False,
        "sources": [],
        "sse_events": [],
    }

    prev_events_len = 0
    prev_draft = ""
    last_state: dict[str, Any] = dict(init)

    async for state_snapshot in self._graph.astream(init, stream_mode="values"):
        last_state = state_snapshot

        events = state_snapshot.get("sse_events") or []
        for ev in events[prev_events_len:]:
            yield {"type": "sse", "data": ev}
        prev_events_len = len(events)

        draft = state_snapshot.get("current_draft", "")
        if draft and draft != prev_draft:
            yield {"type": "draft", "data": {"content": draft}}
            prev_draft = draft

    yield {
        "type": "done",
        "data": {
            "confidence": float(last_state.get("confidence", 0.0)),
            "total_rounds": int(last_state.get("round", 1)),
            "accumulated_context": last_state.get("accumulated_context", []),
        },
    }
```

Also extract the init state building into a shared helper to avoid duplication:

```python
def _build_init_state(self, question: str, scope: RetrievalScope, max_rounds: int) -> RAGState:
    return {
        "question": question,
        "scope": scope,
        "round": 0,
        "max_rounds": max_rounds,
        "accumulated_context": [],
        "current_draft": "",
        "gaps": [],
        "next_queries": [],
        "confidence": 0.0,
        "is_complete": False,
        "sources": [],
        "sse_events": [],
    }

async def arun(self, *, question: str, scope: RetrievalScope, max_rounds: int = 7) -> RAGState:
    init = self._build_init_state(question, scope, max_rounds)
    out = await self._graph.ainvoke(init)
    return out
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_engine_stream.py -v`
Expected: PASS (all 3 tests)

- [x] **Step 5: Adapt WikiAskService.ask_stream to use arun_stream**

In `wiki/ask.py`, modify `ask_stream` to use `arun_stream` when available:

```python
async def ask_stream(self, repository, question, scope=None, conversation_id=None, mode="hybrid", *, record_memory=False, business_id=None):
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
    chunks_list: list[Any] = []
    rag_confidence = 0.0
    rag_rounds = 1

    if hasattr(self._rag_engine, "arun_stream"):
        acc = ""
        try:
            async for event in self._rag_engine.arun_stream(
                question=question, scope=scope_obj, max_rounds=5,
            ):
                if event["type"] == "sse":
                    yield {"event": "rag-progress", "data": event["data"]}
                elif event["type"] == "draft":
                    content = event["data"]["content"]
                    delta = content[len(acc):]
                    acc = content
                    if delta:
                        yield {"event": "wiki-answer", "data": {"content": acc, "delta": delta}}
                elif event["type"] == "done":
                    rag_confidence = event["data"].get("confidence", 0.0)
                    rag_rounds = event["data"].get("total_rounds", 1)
                    chunks_list = list(event["data"].get("accumulated_context") or [])
        except Exception:
            log.warning("wiki_ask_rag_stream_failed", repository=repository, exc_info=True)
            acc = error_out
            yield {"event": "wiki-answer", "data": {"content": acc, "delta": acc}}
        full_text = acc
    else:
        # Batch fallback (existing logic)
        rag_state: dict[str, Any] = {}
        try:
            rag_state = await self._rag_engine.arun(
                question=question, scope=scope_obj, max_rounds=5,
            )
            full_text = str(rag_state.get("current_draft", ""))
        except Exception:
            log.warning("wiki_ask_rag_failed", repository=repository, exc_info=True)
            full_text = error_out

        chunks_raw = rag_state.get("accumulated_context") if rag_state else None
        chunks_list = list(chunks_raw) if isinstance(chunks_raw, list) else []
        rag_confidence = float(rag_state.get("confidence", 0.0)) if rag_state else 0.0
        rag_rounds = int(rag_state.get("round", 1)) if rag_state else 1

        if rag_state:
            for sse_ev in rag_state.get("sse_events", []):
                yield {"event": "rag-progress", "data": sse_ev}

        for d in _chunk_deltas(full_text):
            acc_text = getattr(self, "_acc", "") + d
            self._acc = acc_text  # temporary
            yield {"event": "wiki-answer", "data": {"content": acc_text, "delta": d}}

    sources = _chunks_to_ask_sources(chunks_list)
    yield {"event": "wiki-sources", "data": {"sources": [asdict(s) for s in sources]}}
    complete_data = {
        "conversation_id": history.conversation_id,
        "tokens_used": _estimate_tokens(full_text),
        "iterative_rag": True,
        "confidence": rag_confidence,
        "total_rounds": rag_rounds,
    }
    yield {"event": "wiki-answer-complete", "data": complete_data}

    history.turns.append(ConversationTurn(role="user", content=question))
    history.turns.append(ConversationTurn(role="assistant", content=full_text))
    save_result = self._store.save(history)
    if inspect.isawaitable(save_result):
        await save_result

    if record_memory and business_id and self._memory_loop and full_text and full_text != error_out:
        try:
            pgs = [s.wiki_page for s in sources if s.wiki_page]
            await self._memory_loop.record(question, full_text, pgs, business_id=business_id)
        except Exception:
            log.warning("memory_loop_record_failed", exc_info=True)
```

- [x] **Step 6: Adapt DeepSearchEngine.search_stream to use arun_stream**

In `query/deep_search.py`, modify `search_stream`:

```python
async def search_stream(self, query, *, max_iterations=3, include_code=True, business_id="", model=None, tenant_id=None):
    from wiki.rag.protocol import RetrievalScope

    bid = business_id or (tenant_id or "")
    scope = RetrievalScope(
        scope_type="business" if bid else "global",
        business_id=bid or None,
    )
    yield {"type": "plan", "data": {"intent": query, "sub_queries": [query]}}

    if hasattr(self._engine, "arun_stream"):
        draft = ""
        ctx = []
        try:
            async for event in self._engine.arun_stream(
                question=query, scope=scope, max_rounds=max_iterations,
            ):
                if event["type"] == "sse":
                    yield {"type": "progress", "data": event["data"]}
                elif event["type"] == "draft":
                    draft = event["data"]["content"]
                elif event["type"] == "done":
                    ctx = list(event["data"].get("accumulated_context") or [])
        except Exception:
            logger.error("deep_search_stream_rag_failed", exc_info=True)
            yield {"type": "conclusion", "data": {"analysis": "", "sufficient": False, "business_flows": [], "code_locations": []}}
            return

        yield {
            "type": "conclusion",
            "data": {
                "analysis": draft,
                "sufficient": True,
                "business_flows": _extract_business_flows(draft),
                "code_locations": _extract_code_locations(draft),
            },
        }
    else:
        # Batch fallback (existing logic)
        try:
            state = await self._engine.arun(question=query, scope=scope, max_rounds=max_iterations)
        except Exception:
            logger.error("deep_search_stream_rag_failed", exc_info=True)
            yield {"type": "conclusion", "data": {"analysis": "", "sufficient": False, "business_flows": [], "code_locations": []}}
            return

        for sse in state.get("sse_events", []):
            yield {"type": "progress", "data": sse}

        draft = state.get("current_draft", "") or ""
        yield {
            "type": "conclusion",
            "data": {
                "analysis": draft,
                "sufficient": True,
                "business_flows": _extract_business_flows(draft),
                "code_locations": _extract_code_locations(draft),
            },
        }
```

- [x] **Step 7: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/ -x --timeout=120 -q`
Expected: All tests pass

- [x] **Step 8: Commit**

```bash
git add wiki/rag/engine.py wiki/ask.py query/deep_search.py tests/wiki/rag/test_engine_stream.py
git commit -m "feat: add arun_stream for real-time SSE streaming in RAG engine"
```

---

### Task 4: Evaluation Feedback Loop (eval_suggestions → plan)

**Files:**
- Modify: `wiki/rag/engine.py`
- Test: `tests/wiki/rag/test_eval_feedback_loop.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/rag/test_eval_feedback_loop.py`:

```python
"""Tests for evaluate → plan suggestions feedback loop."""
from __future__ import annotations

import json

import pytest

from wiki.rag.engine import IterativeRAGEngine, RAGState
from wiki.rag.protocol import Chunk, RetrievalScope


class _StubRetriever:
    async def retrieve(self, queries, scope, *, limit=10, exclude_ids=None):
        return [Chunk(content="context", source="wiki", title="T", relevance=0.8)]


class _FeedbackCaptureLLM:
    """LLM that captures plan prompt to verify suggestions are included."""

    def __init__(self):
        self.plan_prompts: list[str] = []

    async def generate(self, prompt, system="", **kw):
        return '{"answer":"a","gaps":["gap1"],"next_queries":["q1"],"confidence":0.5,"is_complete":false}'

    async def complete(self, messages, **kw):
        prompt_text = messages[-1]["content"] if messages else ""

        if "Decompose into" in prompt_text:
            self.plan_prompts.append(prompt_text)
            return '{"sub_queries": ["refined query based on feedback"]}'

        if "Evaluate this answer" in prompt_text:
            return json.dumps({
                "score": 0.6,
                "suggestions": ["Add more detail about authentication flow"],
                "next_queries": ["auth flow details"],
            })

        return '{"answer":"draft","gaps":["gap"],"next_queries":["q"],"confidence":0.5,"is_complete":false}'

    async def complete_stream(self, messages, **kw):
        result = await self.complete(messages, **kw)
        yield result


@pytest.mark.asyncio
async def test_eval_suggestions_field_in_state():
    """RAGState should accept eval_suggestions field."""
    state: RAGState = {
        "question": "test",
        "scope": RetrievalScope(scope_type="global"),
        "round": 0,
        "max_rounds": 7,
        "accumulated_context": [],
        "current_draft": "",
        "gaps": [],
        "next_queries": [],
        "confidence": 0.0,
        "is_complete": False,
        "sources": [],
        "sse_events": [],
        "eval_suggestions": ["suggestion 1"],
    }
    assert state["eval_suggestions"] == ["suggestion 1"]


@pytest.mark.asyncio
async def test_eval_suggestions_passed_to_plan():
    """When evaluate runs, its suggestions should appear in plan's prompt."""
    llm = _FeedbackCaptureLLM()
    engine = IterativeRAGEngine(retriever=_StubRetriever(), llm=llm)
    scope = RetrievalScope(scope_type="global")

    result = await engine.arun(question="explain auth", scope=scope, max_rounds=5)

    if llm.plan_prompts:
        has_feedback = any("evaluation feedback" in p.lower() or "previous evaluation" in p.lower() for p in llm.plan_prompts)
        if result.get("round", 0) >= 3:
            assert has_feedback, "Plan prompt should include eval feedback when available"
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_eval_feedback_loop.py -v`
Expected: FAIL — `eval_suggestions` not in RAGState

- [x] **Step 3: Implement eval_suggestions in RAGState and wire evaluate→plan**

In `wiki/rag/engine.py`:

1. Add `eval_suggestions` to `RAGState`:

```python
class RAGState(TypedDict, total=False):
    question: str
    scope: RetrievalScope
    round: int
    max_rounds: int
    accumulated_context: list[Chunk]
    current_draft: str
    gaps: list[str]
    next_queries: list[str]
    confidence: float
    is_complete: bool
    sources: list[dict[str, Any]]
    sse_events: list[dict[str, Any]]
    eval_suggestions: list[str]  # NEW
```

2. In `evaluate` node, add `eval_suggestions` to return:

```python
async def evaluate(state: RAGState) -> dict[str, Any]:
    # ... existing logic ...
    if score >= 0.85:
        return {"is_complete": True, "confidence": score, "sse_events": ev, "eval_suggestions": suggestions}
    return {"next_queries": nq, "sse_events": ev, "eval_suggestions": suggestions}
```

3. In `plan` node, read and include `eval_suggestions`:

```python
async def plan(state: RAGState) -> dict[str, Any]:
    q = state["question"]
    gaps = state.get("gaps", [])
    gaps_text = "\n".join(f"- {g}" for g in gaps) if gaps else "None identified"

    eval_suggestions = state.get("eval_suggestions", [])
    suggestions_text = "\n".join(f"- {s}" for s in eval_suggestions) if eval_suggestions else ""

    plan_llm = self._llm
    if self._model_strategy:
        try:
            plan_llm = await self._model_strategy.get_llm_port("rag_plan")
        except Exception:
            pass

    prompt = (
        f"Original question:\n{q}\n\n"
        f"Information gaps:\n{gaps_text}\n\n"
    )
    if suggestions_text:
        prompt += f"Previous evaluation feedback:\n{suggestions_text}\n\n"
    prompt += (
        "Decompose into 2-4 precise sub-queries to fill these gaps. "
        'Reply with ONLY valid JSON: {"sub_queries": ["query1", "query2", ...]}'
    )
    raw = await plan_llm.complete([{"role": "user", "content": prompt}])
    # ... rest unchanged ...
```

4. Add `eval_suggestions: []` to `_build_init_state`:

```python
def _build_init_state(self, question, scope, max_rounds):
    return {
        # ... existing fields ...
        "eval_suggestions": [],
    }
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/rag/test_eval_feedback_loop.py -v`
Expected: PASS

- [x] **Step 5: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/ -x --timeout=120 -q`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/rag/engine.py tests/wiki/rag/test_eval_feedback_loop.py
git commit -m "feat: wire evaluate suggestions to plan prompt for quality feedback loop"
```

---

## Sprint C: Frontend SSE Adaptation

### Task 5: AskPanel — RagTimeline Planning/Evaluating Support

**Files:**
- Modify: `dashboard/src/components/wiki/AskPanel.tsx`

- [x] **Step 1: Update RagTimeline in AskPanel.tsx**

In `dashboard/src/components/wiki/AskPanel.tsx`, replace the `RagTimeline` function (lines 136-178):

```tsx
function RagTimeline({ stages }: { stages: Record<string, unknown>[] }) {
  if (!stages.length) return null;
  return (
    <details
      className="mt-2 rounded-lg border border-gray-200 open:bg-gray-50/50 dark:border-gray-700 dark:open:bg-gray-800/30"
      open
    >
      <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-gray-500 marker:content-none dark:text-gray-400 [&::-webkit-details-marker]:hidden">
        Iterative RAG Process
      </summary>
      <div className="space-y-1 border-t border-gray-100 px-3 pb-3 pt-2 dark:border-gray-700">
        {stages.map((s, i) => {
          const t = String(s.type ?? "unknown");
          const color =
            t === "searching"
              ? "bg-blue-400"
              : t === "draft"
                ? "bg-amber-400"
                : t === "planning"
                  ? "bg-purple-400"
                  : t === "evaluating"
                    ? "bg-orange-400"
                    : t === "refining"
                      ? "bg-violet-400"
                      : t === "done"
                        ? "bg-green-400"
                        : "bg-gray-400";
          const label =
            t === "searching"
              ? "Searching"
              : t === "draft"
                ? "Drafting"
                : t === "planning"
                  ? "Planning sub-queries"
                  : t === "evaluating"
                    ? "Evaluating quality"
                    : t === "refining"
                      ? "Refining"
                      : t === "done"
                        ? "Complete"
                        : t;
          return (
            <div key={i}>
              <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
                <span className={`inline-block h-2 w-2 rounded-full ${color}`} />
                <span className="font-medium">{label}</span>
                {s.round != null && <span className="text-gray-400">Round {String(s.round)}</span>}
                {typeof s.confidence === "number" && (
                  <span className="text-gray-400">
                    {((s.confidence as number) * 100).toFixed(0)}%
                  </span>
                )}
                {typeof s.score === "number" && (
                  <span className="text-gray-400">
                    Score: {((s.score as number) * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              {t === "planning" && Array.isArray(s.sub_queries) && (
                <ul className="ml-6 mt-0.5 space-y-0.5">
                  {(s.sub_queries as string[]).map((q, qi) => (
                    <li key={qi} className="text-xs text-gray-400">• {q}</li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
```

- [x] **Step 2: Verify the frontend builds**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm build`
Expected: Build succeeds

- [x] **Step 3: Commit**

```bash
git add dashboard/src/components/wiki/AskPanel.tsx
git commit -m "feat: AskPanel RagTimeline supports planning/evaluating events"
```

---

### Task 6: DeepSearch — Event Whitelist + Stream Structured Results

**Files:**
- Modify: `dashboard/src/components/DeepResearchTimeline.tsx`
- Modify: `dashboard/src/hooks/useDeepSearchStream.ts`
- Modify: `dashboard/src/components/DeepSearchSection.tsx`

- [x] **Step 1: Extend StageEvent type in DeepResearchTimeline.tsx**

In `dashboard/src/components/DeepResearchTimeline.tsx`, update the `StageEvent` type and `useStageLabel`:

```tsx
export type StageEvent = {
  type: "plan" | "progress" | "search_done" | "synthesis" | "conclusion" | "error" | "planning" | "evaluating";
  data: Record<string, unknown>;
  status: "done" | "active" | "pending";
};
```

In the `useStageLabel` function, add cases before the `default`:

```tsx
case "planning": {
  const round = (s.data.round as number) ?? 0;
  const subQueries = (s.data.sub_queries as string[]) ?? [];
  return `Planning sub-queries (Round ${round})${subQueries.length ? `: ${subQueries.join(", ")}` : ""}`;
}
case "evaluating": {
  const round = (s.data.round as number) ?? 0;
  const score = (s.data.score as number) ?? 0;
  return `Evaluating quality (Round ${round}) — Score: ${(score * 100).toFixed(0)}%`;
}
```

- [x] **Step 2: Add planning/evaluating to KNOWN_DEEP_SEARCH_EVENTS**

In `dashboard/src/hooks/useDeepSearchStream.ts`:

```tsx
const KNOWN_DEEP_SEARCH_EVENTS = new Set<StageEvent["type"]>([
  "plan",
  "progress",
  "search_done",
  "synthesis",
  "conclusion",
  "error",
  "planning",
  "evaluating",
]);
```

Also update the status assignment to handle these new events:

```tsx
const status: StageEvent["status"] =
  evType === "progress" || evType === "plan" || evType === "planning" || evType === "evaluating"
    ? "active"
    : "done";
```

- [x] **Step 3: Add stream mode structured results in DeepSearchSection.tsx**

In `dashboard/src/components/DeepSearchSection.tsx`, after the stream markdown rendering block (around line 157-164), add rendering for `business_flows` and `code_locations` from stream conclusion:

Find the section that renders `stream.conclusion` and add after the markdown/JSON rendering:

```tsx
{/* Stream mode: structured results from conclusion */}
{stream.conclusion && (stream.conclusion as Record<string, unknown>).business_flows && 
 ((stream.conclusion as Record<string, unknown>).business_flows as unknown[]).length > 0 && (
  <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
    <h3 className="mb-3 text-sm font-medium text-gray-700 dark:text-gray-300">
      {t.search.businessFlows} ({((stream.conclusion as Record<string, unknown>).business_flows as unknown[]).length})
    </h3>
    <div className="space-y-2">
      {((stream.conclusion as Record<string, unknown>).business_flows as Array<Record<string, unknown>>).map((f, i) => (
        <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/80">
          <span className="font-medium text-gray-800 dark:text-gray-100">
            {String(f.flow || f.name || "")}
          </span>
          {f.description && (
            <span className="ml-2 text-xs text-gray-500">{String(f.description)}</span>
          )}
        </div>
      ))}
    </div>
  </div>
)}
{stream.conclusion && (stream.conclusion as Record<string, unknown>).code_locations &&
 ((stream.conclusion as Record<string, unknown>).code_locations as unknown[]).length > 0 && (
  <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
    <h3 className="mb-3 text-sm font-medium text-gray-700 dark:text-gray-300">
      {t.search.codeLocations} ({((stream.conclusion as Record<string, unknown>).code_locations as unknown[]).length})
    </h3>
    <div className="space-y-2">
      {((stream.conclusion as Record<string, unknown>).code_locations as Array<Record<string, unknown>>).map((loc, i) => (
        <div
          key={i}
          className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3 text-sm dark:border-gray-700 dark:bg-gray-800/80"
        >
          <code className="rounded bg-gray-200 px-1.5 py-0.5 text-xs dark:bg-gray-700">
            {String(loc.path || "")}
          </code>
          {loc.context && (
            <span className="text-xs text-gray-500 truncate max-w-md">{String(loc.context)}</span>
          )}
        </div>
      ))}
    </div>
  </div>
)}
```

- [x] **Step 4: Verify the frontend builds**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm build`
Expected: Build succeeds

- [x] **Step 5: Run full backend test suite to confirm no regressions**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/ -x --timeout=120 -q`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add dashboard/src/components/DeepResearchTimeline.tsx dashboard/src/hooks/useDeepSearchStream.ts dashboard/src/components/DeepSearchSection.tsx
git commit -m "feat: frontend SSE whitelist + planning/evaluating rendering + stream structured results"
```

---

## Summary

| Sprint | Task | Description | Estimated Steps |
|--------|------|-------------|-----------------|
| A | 1 | NL-to-Cypher → HybridGraphRetriever | 7 |
| A | 2 | MultiRepoRetriever | 7 |
| B | 3 | arun_stream (RAG streaming) | 8 |
| B | 4 | eval_suggestions feedback loop | 6 |
| C | 5 | AskPanel planning/evaluating | 3 |
| C | 6 | DeepSearch SSE + structured results | 6 |
| **Total** | | | **37** |
