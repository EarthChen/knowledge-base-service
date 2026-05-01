# Phase 6 实施计划 — 统一迭代 RAG 引擎 + 动态模型策略

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一三套搜索系统为 IterativeRAGEngine，实现 Dashboard 可配置的模型策略路由

**Architecture:** LangGraph 驱动的自反馈迭代 RAG 引擎 + SettingsStore 热重载的 Provider 池和任务策略路由 + 复杂度评估器联动 + code_structure 语义分组 + MCP 增强

**Tech Stack:** Python 3.12, LangGraph, FastAPI, React 19, TanStack Query, FalkorDB, SQLite (SettingsStore)

---

## 规划文件结构（相对 `knowledge-base-service/`）

```text
wiki/rag/
  __init__.py
  protocol.py          # Chunk, Source, RetrievalScope, Retriever Protocol
  events.py            # SSE 事件构造与校验（与设计 §2.7 对齐）
  wiki_retriever.py
  code_retriever.py
  composite_retriever.py
  engine.py            # IterativeRAGEngine (LangGraph StateGraph)
wiki/model_strategy.py
tests/wiki/rag/
  test_protocol.py
  test_wiki_retriever.py
  test_code_retriever.py
  test_composite_retriever.py
  test_events.py
  test_engine.py
tests/wiki/test_model_strategy.py
# 既有改动点（节选）
wiki/ask.py
wiki/deep_research.py
wiki/pipeline_orchestrator.py
wiki/pipeline_nodes.py
wiki/domain_complexity.py
wiki/tree_linker.py
wiki/mcp_tools.py
query/deep_search.py
api/routes/settings_routes.py
api/routes/provider_routes.py
api/routes/wiki_ask_routes.py
services/settings_service.py
llm/base_provider.py
llm/provider_factory.py
config.py
dashboard/src/components/wiki/AskPanel.tsx
dashboard/src/hooks/useWikiAsk.ts
dashboard/src/hooks/useDeepSearchStream.ts
dashboard/src/components/DeepSearchSection.tsx
dashboard/src/components/settings/SystemConfigPanel.tsx
dashboard/src/components/settings/sections/LLMProviderPoolSection.tsx   # 新建
dashboard/src/components/settings/sections/ModelStrategySection.tsx    # 新建
e2e/…（按项目现有 Playwright 布局）
docs/ARCHITECTURE.md
docs/MCP-INTEGRATION.md
docs/superpowers/…/DEEP_ANALYSIS*.md（或既有分析报告路径）
```

### 依赖顺序（Task 拓扑）

1. **Sprint 1:** `protocol` → `events` → `wiki_retriever` / `code_retriever`（可并行）→ `composite_retriever` → **`engine` 依赖 `events`：可先提交 Task 6 再实现 Task 5，或在同一 commit 中包含 `wiki/rag/events.py`** → 聚合测试。
2. **Sprint 2:** `ModelStrategy` 依赖 `SettingsStore` + `LLMProviderFactory`；`HOT_RELOAD_KEYS` 与 Dashboard API 并行；`pipeline_orchestrator` / `pipeline_nodes` 在 `ModelStrategy` 可注入后改。
3. **Sprint 3:** `IterativeRAGEngine` + `ModelStrategy` 齐备后迁移 `WikiAskService`、`DeepSearchEngine`、`DeepResearchService`，再改前端与路由。
4. **Sprint 4:** 复杂度与 `tree_linker`、MCP 可部分并行，但 **A1/A5 依赖** `CompositeRetriever` 与引擎稳定接口。
5. **Sprint 5:** 文档与 E2E 最后收口。

---

## Sprint 1 — RAG 基础设施（Task 1–7）

### Task 1 — `Retriever` 协议与 `Chunk` / `RetrievalScope` / `Source`

**Files**

- **Create:** `wiki/rag/__init__.py`, `wiki/rag/protocol.py`
- **Create:** `tests/wiki/rag/test_protocol.py`

**Step 1: 写失败测试（完整测试代码）**

```python
# tests/wiki/rag/test_protocol.py
from __future__ import annotations

import pytest

from wiki.rag.protocol import Chunk, RetrievalScope, Source


def test_chunk_dataclass_fields() -> None:
    c = Chunk(
        content="body",
        source="wiki:/p",
        title="T",
        relevance=0.9,
        metadata={"k": "v"},
    )
    assert c.content == "body"
    assert c.metadata == {"k": "v"}


def test_retrieval_scope_repository_global() -> None:
    scope = RetrievalScope(scope_type="repository", repository="repo-a")
    assert scope.scope_type == "repository"
    assert scope.repository == "repo-a"
    assert scope.page_path is None


def test_source_for_citations() -> None:
    s = Source(kind="wiki", title="Auth", path="/auth", relevance=0.88, extra={"uid": "1"})
    assert s.kind == "wiki"
    assert s.path == "/auth"


def test_chunk_metadata_default_factory() -> None:
    c = Chunk(content="a", source="s", title="t", relevance=0.1)
    c.metadata["x"] = 1
    c2 = Chunk(content="a", source="s", title="t", relevance=0.1)
    assert c2.metadata == {}
```

**Step 2: 运行测试验证失败**

```bash
cd knowledge-base-service
uv run pytest tests/wiki/rag/test_protocol.py -v
```

**预期输出:** `ModuleNotFoundError: No module named 'wiki.rag'` 或 import `wiki.rag.protocol` 失败。

**Step 3: 写最小实现（完整代码）**

```python
# wiki/rag/__init__.py
from wiki.rag.protocol import Chunk, RetrievalScope, Retriever, Source

__all__ = ["Chunk", "RetrievalScope", "Retriever", "Source"]
```

```python
# wiki/rag/protocol.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ScopeType = Literal["page", "business", "repository", "global"]


@dataclass
class Chunk:
    content: str
    source: str
    title: str
    relevance: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Source:
    """Citation / provenance for SSE and final answer."""

    kind: Literal["wiki", "code", "graph"]
    title: str
    path: str
    relevance: float
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalScope:
    scope_type: ScopeType
    page_path: str | None = None
    business_id: str | None = None
    repository: str | None = None


class Retriever(Protocol):
    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]: ...
```

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/rag/test_protocol.py -v
```

**Step 5: Commit**

```bash
git add wiki/rag/__init__.py wiki/rag/protocol.py tests/wiki/rag/test_protocol.py
git commit -m "feat(rag): add Retriever protocol and core datatypes"
```

---

### Task 2 — `WikiRetriever`（适配 `WikiSearchService`）

**Files**

- **Create:** `wiki/rag/wiki_retriever.py`
- **Create:** `tests/wiki/rag/test_wiki_retriever.py`

**Step 1: 写失败测试（完整测试代码）**

```python
# tests/wiki/rag/test_wiki_retriever.py
from __future__ import annotations

import pytest

from wiki.rag.protocol import RetrievalScope
from wiki.rag.wiki_retriever import WikiRetriever


class _FakeSearch:
    def __init__(self) -> None:
        self.called: list[tuple[str, str]] = []

    async def search(
        self,
        repository: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        min_score: float = 0.0,
        *,
        scope: str | None = None,
    ) -> object:
        self.called.append((repository, query))
        from wiki.search import SearchResponse, SearchResult

        return SearchResponse(
            results=[
                SearchResult(
                    page_path="/a",
                    title="A",
                    score=0.9,
                    snippet="hi",
                    source_locations=[],
                    context={},
                )
            ],
            query_expansion={},
            total=1,
        )


@pytest.mark.asyncio
async def test_wiki_retriever_maps_search_results_to_chunks() -> None:
    fake = _FakeSearch()
    r = WikiRetriever(fake, default_repository="repo1")
    scope = RetrievalScope(scope_type="repository", repository="repo1")
    chunks = await r.retrieve(["q1"], scope, limit=5)
    assert len(chunks) == 1
    assert chunks[0].title == "A"
    assert chunks[0].source.startswith("wiki:")
    assert ("repo1", "q1") in fake.called
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/wiki/rag/test_wiki_retriever.py -v
```

**预期输出:** `ModuleNotFoundError` 或 `WikiRetriever` 缺少 `retrieve`。

**Step 3: 写最小实现（完整代码）**

```python
# wiki/rag/wiki_retriever.py
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from log import get_logger
from wiki.rag.protocol import Chunk, RetrievalScope

log = get_logger(__name__)


@runtime_checkable
class _WikiSearchLike(Protocol):
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


class WikiRetriever:
    def __init__(
        self,
        wiki_search: _WikiSearchLike,
        *,
        default_repository: str = "",
        search_mode: str = "hybrid",
    ) -> None:
        self._search = wiki_search
        self._default_repository = default_repository
        self._mode = search_mode

    def _repo(self, scope: RetrievalScope) -> str:
        return (scope.repository or self._default_repository or "").strip()

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        repo = self._repo(scope)
        if not repo:
            log.warning("wiki_retriever_missing_repository")
            return []
        out: list[Chunk] = []
        seen: set[str] = set()
        for q in queries:
            if not q.strip():
                continue
            resp = await self._search.search(
                repo,
                q,
                mode=self._mode,
                limit=limit,
                min_score=0.0,
                scope=scope.page_path,
            )
            results = getattr(resp, "results", None) or []
            for sr in results:
                path = str(getattr(sr, "page_path", "") or "")
                if exclude_ids and path in exclude_ids:
                    continue
                key = path or str(getattr(sr, "title", ""))
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    Chunk(
                        content=str(getattr(sr, "snippet", "") or ""),
                        source=f"wiki:{path}",
                        title=str(getattr(sr, "title", "") or path),
                        relevance=float(getattr(sr, "score", 0.0) or 0.0),
                        metadata={"page_path": path, "mode": self._mode},
                    )
                )
                if len(out) >= limit:
                    return out
        return out
```

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/rag/test_wiki_retriever.py -v
```

**Step 5: Commit**

```bash
git add wiki/rag/wiki_retriever.py tests/wiki/rag/test_wiki_retriever.py wiki/rag/__init__.py
git commit -m "feat(rag): add WikiRetriever wrapping WikiSearchService"
```

---

### Task 3 — `CodeRetriever`（适配 `HybridQueryService`）

**Files**

- **Create:** `wiki/rag/code_retriever.py`
- **Create:** `tests/wiki/rag/test_code_retriever.py`

**Step 1: 写失败测试（完整测试代码）**

```python
# tests/wiki/rag/test_code_retriever.py
from __future__ import annotations

import pytest

from wiki.rag.protocol import RetrievalScope
from wiki.rag.code_retriever import CodeRetriever


class _HybridStub:
    async def search_with_context(self, *args: object, **kwargs: object) -> dict:
        return {
            "results": [
                {
                    "name": "fn",
                    "file": "a.py",
                    "type": "Function",
                    "rrf_score": 0.82,
                    "summary": "does work",
                }
            ],
            "total": 1,
        }


@pytest.mark.asyncio
async def test_code_retriever_merges_query_list() -> None:
    h = _HybridStub()
    r = CodeRetriever(h)
    scope = RetrievalScope(scope_type="global")
    chunks = await r.retrieve(["login"], scope, limit=5)
    assert len(chunks) == 1
    assert chunks[0].title == "fn"
    assert "code:" in chunks[0].source
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/wiki/rag/test_code_retriever.py -v
```

**Step 3: 写最小实现（完整代码）**

```python
# wiki/rag/code_retriever.py
from __future__ import annotations

from typing import Any

from log import get_logger
from query.hybrid_query import HybridQueryService
from wiki.rag.protocol import Chunk, RetrievalScope

log = get_logger(__name__)


class CodeRetriever:
    """Retrieval over code KB via HybridQueryService."""

    def __init__(
        self,
        hybrid: HybridQueryService,
        *,
        repository_hint: str | None = None,
    ) -> None:
        self._hybrid = hybrid
        self._repository_hint = repository_hint

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        out: list[Chunk] = []
        seen: set[str] = set()
        repo = (scope.repository or self._repository_hint or "").strip() or None

        for q in queries:
            if not q.strip():
                continue
            try:
                payload = await self._hybrid.search_with_context(
                    q,
                    k=min(limit, 20),
                    limit=limit,
                    offset=0,
                    repository=repo,
                )
            except Exception as exc:
                log.warning("code_retriever_hybrid_failed", error=str(exc))
                continue

            rows = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue

            for row in rows:
                if not isinstance(row, dict):
                    continue
                path = str(row.get("file") or row.get("path") or "")
                name = str(row.get("name") or path)
                uid = f"{path}:{name}"
                if exclude_ids and uid in exclude_ids:
                    continue
                if uid in seen:
                    continue
                seen.add(uid)
                score = row.get("rrf_score", row.get("score", 0.0))
                try:
                    rel = float(score) if score is not None else 0.0
                except (TypeError, ValueError):
                    rel = 0.0
                summary = str(row.get("summary") or row.get("snippet") or "")
                out.append(
                    Chunk(
                        content=summary,
                        source=f"code:{path}",
                        title=name,
                        relevance=rel,
                        metadata={"row": row},
                    )
                )
                if len(out) >= limit:
                    return out
        return out
```

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/rag/test_code_retriever.py -v
```

**Step 5: Commit**

```bash
git add wiki/rag/code_retriever.py tests/wiki/rag/test_code_retriever.py
git commit -m "feat(rag): add CodeRetriever on HybridQueryService"
```

---

### Task 4 — `CompositeRetriever`

**Files**

- **Create:** `wiki/rag/composite_retriever.py`
- **Create:** `tests/wiki/rag/test_composite_retriever.py`

**Step 1: 写失败测试（完整测试代码）**

```python
# tests/wiki/rag/test_composite_retriever.py
from __future__ import annotations

import pytest

from wiki.rag.protocol import Chunk, RetrievalScope, Retriever
from wiki.rag.composite_retriever import CompositeRetriever


class _MemRetriever:
    def __init__(self, tag: str, score: float) -> None:
        self.tag = tag
        self.score = score

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                content=self.tag,
                source=f"{self.tag}:x",
                title=self.tag,
                relevance=self.score,
                metadata={},
            )
        ]


@pytest.mark.asyncio
async def test_composite_merges_and_sorts_by_relevance() -> None:
    a = _MemRetriever("wiki", 0.5)
    b = _MemRetriever("code", 0.9)
    c = CompositeRetriever([a, b])
    chunks = await c.retrieve(["q"], RetrievalScope(scope_type="global"), limit=10)
    assert [x.title for x in chunks] == ["code", "wiki"]
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/wiki/rag/test_composite_retriever.py -v
```

**Step 3: 写最小实现（完整代码）**

```python
# wiki/rag/composite_retriever.py
from __future__ import annotations

from wiki.rag.protocol import Chunk, RetrievalScope, Retriever


class CompositeRetriever:
    def __init__(self, children: list[Retriever]) -> None:
        self._children = children

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        merged: list[Chunk] = []
        for child in self._children:
            part = await child.retrieve(
                queries, scope, limit=limit, exclude_ids=exclude_ids
            )
            merged.extend(part)
        merged.sort(key=lambda c: c.relevance, reverse=True)
        return merged[:limit]
```

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/rag/test_composite_retriever.py -v
```

**Step 5: Commit**

```bash
git add wiki/rag/composite_retriever.py tests/wiki/rag/test_composite_retriever.py
git commit -m "feat(rag): add CompositeRetriever merging multiple retrievers"
```

---

### Task 5 — `IterativeRAGEngine`（LangGraph）

**Files**

- **Create:** `wiki/rag/engine.py`
- **Create:** `tests/wiki/rag/test_engine.py`

**Step 1: 写失败测试（完整测试代码）**

```python
# tests/wiki/rag/test_engine.py
from __future__ import annotations

from typing import Any

import pytest

from wiki.rag.protocol import Chunk, RetrievalScope, Retriever
from wiki.rag.engine import IterativeRAGEngine


class _FixedRetriever:
    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                content="ctx",
                source="wiki:/x",
                title="t",
                relevance=0.9,
                metadata={},
            )
        ]


class _EchoLLM:
    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return (
            '{"answer":"ok","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'
        )


@pytest.mark.asyncio
async def test_engine_runs_single_round_and_completes() -> None:
    engine = IterativeRAGEngine(
        retriever=_FixedRetriever(),
        plan_llm=_EchoLLM(),
        generate_llm=_EchoLLM(),
    )
    state = await engine.arun(
        question="what?",
        scope=RetrievalScope(scope_type="global"),
        max_rounds=3,
    )
    assert state["is_complete"] is True
    assert state["current_draft"]
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/wiki/rag/test_engine.py -v
```

**Step 3: 写最小实现（完整代码）**

实现要点（与设计 §2.3–§2.6 对齐）：使用 `langgraph.graph.StateGraph`，节点最少包含 `initial_search` → `generate_draft` → `check_complete`；条件边在 `is_complete` 或 `round >= max_rounds` 时进入 `final_answer`，否则 `dynamic_retrieve` 后回 `generate_draft`。LLM 输出 JSON 解析失败时走设计 §2.6.2 回退分支。

```python
# wiki/rag/engine.py
from __future__ import annotations

import json
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from log import get_logger
from wiki.rag.events import rag_sse_append
from wiki.rag.protocol import Chunk, RetrievalScope, Retriever

log = get_logger(__name__)


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
    prev_gaps_len: int


class _LLM:
    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


def _parse_reflection(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


class IterativeRAGEngine:
    def __init__(
        self,
        *,
        retriever: Retriever,
        plan_llm: _LLM,
        generate_llm: _LLM,
        evaluate_llm: _LLM | None = None,
    ) -> None:
        self._retriever = retriever
        self._plan_llm = plan_llm
        self._gen_llm = generate_llm
        self._eval_llm = evaluate_llm or generate_llm
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(RAGState)

        async def initial_search(state: RAGState) -> dict[str, Any]:
            q = state["question"]
            scope = state["scope"]
            chunks = await self._retriever.retrieve([q], scope, limit=10)
            ev = rag_sse_append(state, "searching", {"queries": [q], "sources_count": len(chunks)})
            return {
                "accumulated_context": chunks,
                "round": 1,
                "sse_events": ev,
            }

        async def generate_draft(state: RAGState) -> dict[str, Any]:
            q = state["question"]
            ctx = state.get("accumulated_context") or []
            ctx_text = "\n\n".join(f"### {c.title}\n{c.content}" for c in ctx[:50])
            prompt = (
                f"Question:\n{q}\n\nContext:\n{ctx_text}\n\n"
                "Reply with ONLY valid JSON: "
                '{"answer":string,"gaps":string[],"next_queries":string[],'
                '"confidence":number,"is_complete":bool}'
            )
            raw = await self._gen_llm.complete(
                [{"role": "user", "content": prompt}],
                **{"model": None},
            )
            data = _parse_reflection(raw)
            answer = str(data.get("answer") or raw)
            gaps = [str(x) for x in data.get("gaps") or [] if str(x).strip()]
            nq = [str(x) for x in data.get("next_queries") or [] if str(x).strip()]
            try:
                conf = float(data.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            is_complete = bool(data.get("is_complete", False))
            if conf >= 0.85 and not is_complete:
                is_complete = True
            ev = state.get("sse_events") or []
            ev = rag_sse_append(
                {"sse_events": ev},
                "draft",
                {"round": state.get("round", 1), "content": answer[:2000], "confidence": conf},
            )
            return {
                "current_draft": answer,
                "gaps": gaps,
                "next_queries": nq,
                "confidence": conf,
                "is_complete": is_complete,
                "sse_events": ev,
            }

        async def dynamic_retrieve(state: RAGState) -> dict[str, Any]:
            nq = state.get("next_queries") or []
            scope = state["scope"]
            new_chunks = await self._retriever.retrieve(nq, scope, limit=10) if nq else []
            merged = list(state.get("accumulated_context") or [])
            merged.extend(new_chunks)
            ev = rag_sse_append(
                state,
                "refining",
                {"round": state.get("round", 1), "reason": "follow-up retrieval"},
            )
            return {
                "accumulated_context": merged,
                "round": int(state.get("round", 1)) + 1,
                "sse_events": ev,
            }

        async def finalize(state: RAGState) -> dict[str, Any]:
            ev = rag_sse_append(
                state,
                "done",
                {
                    "final_answer": state.get("current_draft", ""),
                    "total_rounds": state.get("round", 1),
                    "confidence": state.get("confidence", 0.0),
                },
            )
            return {"sse_events": ev}

        graph.add_node("initial_search", initial_search)  # type: ignore[arg-type]
        graph.add_node("generate_draft", generate_draft)  # type: ignore[arg-type]
        graph.add_node("dynamic_retrieve", dynamic_retrieve)  # type: ignore[arg-type]
        graph.add_node("finalize", finalize)  # type: ignore[arg-type]

        graph.set_entry_point("initial_search")
        graph.add_edge("initial_search", "generate_draft")

        def route_after_draft(s: RAGState) -> Literal["finalize", "dynamic_retrieve"]:
            if s.get("is_complete") or int(s.get("round", 1)) >= int(s.get("max_rounds", 7)):
                return "finalize"
            if not (s.get("next_queries") or []):
                return "finalize"
            if int(s.get("round", 1)) >= int(s.get("max_rounds", 7)):
                return "finalize"
            return "dynamic_retrieve"

        graph.add_conditional_edges("generate_draft", route_after_draft)
        graph.add_edge("dynamic_retrieve", "generate_draft")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def arun(
        self,
        *,
        question: str,
        scope: RetrievalScope,
        max_rounds: int = 7,
    ) -> RAGState:
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
        out = await self._graph.ainvoke(init)
        return out  # type: ignore[return-value]
```

**依赖提醒:** Task 5 的 `rag_sse_append` 来自 Task 6；实施时 **先合并 Task 6 的 `events.py`** 或将 Task 5 与 Task 6 在同一 PR 中提交。

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/rag/test_engine.py -v
```

**Step 5: Commit**

```bash
git add wiki/rag/engine.py tests/wiki/rag/test_engine.py
git commit -m "feat(rag): add IterativeRAGEngine LangGraph loop"
```

---

### Task 6 — SSE 事件协议（`wiki/rag/events.py`）

**Files**

- **Create:** `wiki/rag/events.py`
- **Create:** `tests/wiki/rag/test_events.py`

**Step 1: 写失败测试（完整测试代码）**

```python
# tests/wiki/rag/test_events.py
from __future__ import annotations

from wiki.rag.events import rag_sse_append, sse_thinking_start


def test_sse_thinking_start_shape() -> None:
    e = sse_thinking_start(round_no=2, max_rounds=7)
    assert e["type"] == "thinking_start"
    assert e["round"] == 2


def test_rag_sse_append_preserves_list() -> None:
    base = {"sse_events": [{"type": "x"}]}
    out = rag_sse_append(base, "draft", {"round": 1})
    assert len(out) == 2
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/wiki/rag/test_events.py -v
```

**Step 3: 写最小实现（完整代码）**

```python
# wiki/rag/events.py
from __future__ import annotations

from typing import Any


def sse_thinking_start(*, round_no: int, max_rounds: int) -> dict[str, Any]:
    return {"type": "thinking_start", "round": round_no, "max_rounds": max_rounds}


def rag_sse_append(
    state: dict[str, Any],
    typ: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Append SSE event; mirrors design §2.7 types."""
    events: list[dict[str, Any]] = list(state.get("sse_events") or [])
    body: dict[str, Any] = {"type": typ, **payload}
    events.append(body)
    return events
```

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/rag/test_events.py -v
```

函数参数使用 `round_no`（避免与内置 `round` 冲突）；SSE JSON 载荷键名仍为 `"round"`，与前端一致。

**Step 5: Commit**

```bash
git add wiki/rag/events.py tests/wiki/rag/test_events.py
git commit -m "feat(rag): add unified RAG SSE event helpers"
```

---

### Task 7 — Sprint 1 聚合测试与导出

**Files**

- **Modify:** `wiki/rag/__init__.py`（导出 engine、retrievers、events）
- **Create:** `tests/wiki/rag/test_rag_smoke.py`

**Step 1: 写失败测试**

```python
# tests/wiki/rag/test_rag_smoke.py
from __future__ import annotations

import wiki.rag as rag


def test_package_exports() -> None:
    assert hasattr(rag, "IterativeRAGEngine")
    assert hasattr(rag, "WikiRetriever")
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/wiki/rag/test_rag_smoke.py -v
```

**Step 3: 写最小实现**

```python
# wiki/rag/__init__.py 补充
from wiki.rag.code_retriever import CodeRetriever
from wiki.rag.composite_retriever import CompositeRetriever
from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.events import rag_sse_append, sse_thinking_start
from wiki.rag.protocol import Chunk, RetrievalScope, Retriever, Source
from wiki.rag.wiki_retriever import WikiRetriever

__all__ = [
    "Chunk",
    "CodeRetriever",
    "CompositeRetriever",
    "IterativeRAGEngine",
    "rag_sse_append",
    "Retriever",
    "RetrievalScope",
    "Source",
    "sse_thinking_start",
    "WikiRetriever",
]
```

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/rag/ -v
```

**Step 5: Commit**

```bash
git add wiki/rag/__init__.py tests/wiki/rag/test_rag_smoke.py
git commit -m "chore(rag): export public RAG package API"
```

---

## Sprint 2 — 模型策略（Task 8–14）

### Task 8 — `ModelStrategy` 类

**Files**

- **Create:** `wiki/model_strategy.py`
- **Create:** `tests/wiki/test_model_strategy.py`

**Step 1: 写失败测试（完整测试代码）**

```python
# tests/wiki/test_model_strategy.py
from __future__ import annotations

import json

import pytest

from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory, ProviderConfig
from store.settings_store import SettingsStore
from wiki.model_strategy import ModelStrategy


class _StubProvider:
    @property
    def provider_name(self) -> str:
        return "stub"

    @property
    def supports_streaming(self) -> bool:
        return False

    @property
    def max_context_tokens(self) -> int:
        return 128000

    async def complete(self, messages, **kwargs):
        return "ok"

    async def complete_json(self, messages, schema, **kwargs):
        return {}

    async def complete_stream(self, messages, **kwargs):
        if False:
            yield ""

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_resolve_uses_db_strategy(tmp_path) -> None:
    db = str(tmp_path / "s.db")
    store = SettingsStore(db_path=db)
    await store.upsert(
        "llm.strategy.classification",
        json.dumps({"provider": "gateway", "model": "m-mini"}),
        "llm",
    )
    cfg = ProviderConfig(default_provider="gateway", providers={})
    factory = LLMProviderFactory(cfg, gateway_provider=_StubProvider())
    ms = ModelStrategy(store, factory, default_provider="gateway", default_model="m-default")
    p, m = await ms.resolve("classification")
    assert p == "gateway"
    assert m == "m-mini"
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/wiki/test_model_strategy.py -v
```

**Step 3: 写最小实现（完整代码）**

```python
# wiki/model_strategy.py
from __future__ import annotations

import json
from typing import Any

from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory
from store.settings_store import SettingsStore
from wiki.context import LLMPort


class ModelStrategy:
    def __init__(
        self,
        settings_store: SettingsStore,
        provider_factory: LLMProviderFactory,
        default_provider: str,
        default_model: str,
    ) -> None:
        self._store = settings_store
        self._factory = provider_factory
        self._default_provider = default_provider
        self._default_model = default_model

    async def resolve(
        self,
        task_type: str,
        complexity_override: tuple[str, str] | None = None,
    ) -> tuple[str, str]:
        raw = await self._store.get(f"llm.strategy.{task_type}")
        if raw:
            cfg = json.loads(raw)
            return str(cfg["provider"]), str(cfg["model"])
        if complexity_override:
            return complexity_override[0], complexity_override[1]
        return self._default_provider, self._default_model

    async def get_llm_port(self, task_type: str) -> LLMPort:
        provider_name, model = await self.resolve(task_type)
        provider = self._factory.get_provider(provider_name)
        return _LLMPortWithDefault(LLMPortBridge(provider), default_model=model)


class _LLMPortWithDefault:
    """Wraps LLMPortBridge so wiki.context.LLMPort.generate uses routed model."""

    def __init__(self, inner: LLMPortBridge, *, default_model: str) -> None:
        self._inner = inner
        self._default_model = default_model

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        m = model or self._default_model
        return await self._inner.generate(
            prompt,
            system,
            model=m,
            max_tokens=max_tokens,
            extra_params={"reasoning_effort": reasoning_effort} if reasoning_effort else {},
        )
```

**注意:** `LLMPortBridge.generate` 的 `extra_params` 合并需与 `llm/base_provider.py` 一致；若当前实现不接受 `reasoning_effort`，应在 Task 9 扩展 `LLMPortBridge` 签名（见 Task 14 联动）。

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/wiki/test_model_strategy.py -v
```

**Step 5: Commit**

```bash
git add wiki/model_strategy.py tests/wiki/test_model_strategy.py
git commit -m "feat(llm): add ModelStrategy with SettingsStore resolution"
```

---

### Task 9 — Provider 池 Schema + `SENSITIVE_KEYS` 扩展

**Files**

- **Modify:** `services/settings_service.py`
- **Modify:** `store/settings_store.py`（如需 helper；可选 `get_by_prefix`）
- **Create:** `tests/services/test_llm_provider_pool_settings.py`

**Step 1: 写失败测试**

```python
# tests/services/test_llm_provider_pool_settings.py
from __future__ import annotations

import json

import pytest

from services.settings_service import SettingsService, SENSITIVE_KEYS
from store.settings_store import SettingsStore


@pytest.mark.asyncio
async def test_llm_providers_key_is_sensitive(tmp_path) -> None:
    assert "llm.providers" in SENSITIVE_KEYS
    db = str(tmp_path / "x.db")
    store = SettingsStore(db_path=db)
    secret = json.dumps({"openai": {"api_key": "sk-secret"}})
    await store.upsert("llm.providers", secret, "llm")
    svc = SettingsService(store)
    merged = await svc.get_all_merged()
    flat = merged.get("llm", {}).get("llm.providers", {})
    assert flat.get("sensitive") is True
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/services/test_llm_provider_pool_settings.py -v
```

**Step 3: 写最小实现**

在 `SENSITIVE_KEYS` 中加入 `"llm.providers"`；`get_all_merged` 对 value 为 JSON 且内含 `api_key` 的嵌套脱敏可在 `mask_value` 层扩展，或 **将整个 `llm.providers` 值视为敏感** 只做存取加密（与现有 `encrypt_value` 路径一致）。

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/services/test_llm_provider_pool_settings.py -v
```

**Step 5: Commit**

```bash
git add services/settings_service.py tests/services/test_llm_provider_pool_settings.py
git commit -m "feat(settings): treat llm.providers as sensitive stored settings"
```

---

### Task 10 — `HOT_RELOAD_KEYS` 扩展

**Files**

- **Modify:** `api/routes/settings_routes.py`
- **Create:** `tests/api/test_settings_hot_reload.py`

**Step 1: 写失败测试**

```python
# tests/api/test_settings_hot_reload.py
from __future__ import annotations

from api.routes.settings_routes import HOT_RELOAD_KEYS


def test_llm_keys_hot_reload() -> None:
    assert "llm.providers" in HOT_RELOAD_KEYS
    assert "llm.strategy.classification" in HOT_RELOAD_KEYS
```

**Step 2: 运行测试验证失败**

```bash
uv run pytest tests/api/test_settings_hot_reload.py -v
```

**Step 3: 写最小实现**

```python
# api/routes/settings_routes.py 片段
HOT_RELOAD_KEYS = frozenset({
    "wiki.auto_update_on_index",
    "llm.providers",
    "llm.strategy.classification",
    "llm.strategy.generation",
    "llm.strategy.reasoning",
    "llm.strategy.evaluation",
    "llm.strategy.heal",
    "llm.strategy.diagram",
    "llm.strategy.rag_plan",
    "llm.strategy.rag_generate",
    "llm.strategy.overview",
    "llm.strategy.context",
})
```

**Step 4: 运行测试验证通过**

```bash
uv run pytest tests/api/test_settings_hot_reload.py -v
```

**Step 5: Commit**

```bash
git add api/routes/settings_routes.py tests/api/test_settings_hot_reload.py
git commit -m "feat(settings): hot-reload llm provider pool and strategy keys"
```

---

### Task 11 — Pipeline 注入 `ModelStrategy`

**Files**

- **Modify:** `wiki/pipeline_orchestrator.py`
- **Modify:** `wiki/pipeline_graph.py`（若 configurable 键需在编译时声明）
- **Create:** `tests/wiki/test_pipeline_model_strategy_config.py`

**Step 1: 写失败测试**

断言 `run_langgraph_pipeline` 将 `config={"configurable": {..., "model_strategy": obj}}` 传入 `ainvoke`（与现有 `llm` 并列）。

**Step 3: 写最小实现**

扩展 `run_langgraph_pipeline(..., model_strategy: Any | None = None)`，`ainvoke` 的 `configurable` 加入 `"model_strategy": model_strategy`。

**Step 4**

```bash
uv run pytest tests/wiki/test_pipeline_model_strategy_config.py -v
```

**Step 5: Commit**

```bash
git add wiki/pipeline_orchestrator.py wiki/pipeline_graph.py tests/wiki/test_pipeline_model_strategy_config.py
git commit -m "feat(pipeline): pass ModelStrategy through LangGraph configurable"
```

---

### Task 12 — `pipeline_nodes` 使用 `ModelStrategy`

**Files**

- **Modify:** `wiki/pipeline_nodes.py`（所有 `config.get("configurable", {}).get("llm")` 路径旁路：按节点选 `task_type` 调 `model_strategy.get_llm_port`）
- **Modify:** `tests/wiki/unit/test_pipeline_nodes_smoke.py`（新建或扩展现有）

**Step 1:** 针对 `classify_domains_node` 用 fake `ModelStrategy` 返回固定 `LLMPort` mock，断言 `CrossRepoBusinessDomainPlanner` 收到该 port。

**Step 3:** 在节点内：

```python
cfg = config or {}
conf = cfg.get("configurable") or {}
ms = conf.get("model_strategy")
llm_legacy = conf.get("llm")
llm = await ms.get_llm_port("classification") if ms is not None else llm_legacy
```

**Step 4**

```bash
uv run pytest tests/wiki/unit/test_pipeline_nodes_smoke.py -v
```

**Step 5: Commit**

```bash
git commit -am "feat(pipeline): route wiki pipeline LLM calls via ModelStrategy"
```

---

### Task 13 — Dashboard Provider 池 UI

**Files**

- **Create:** `dashboard/src/components/settings/sections/LLMProviderPoolSection.tsx`
- **Modify:** `dashboard/src/components/settings/SystemConfigPanel.tsx`
- **Modify:** `dashboard/src/hooks/settingsCategory.ts`（如有需要注册 `llm` 类别显示名）
- **Create:** `dashboard/src/components/settings/sections/LLMProviderPoolSection.test.tsx`

**Step 1: 写失败测试（Vitest + Testing Library）**

```tsx
// dashboard/src/components/settings/sections/LLMProviderPoolSection.test.tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import LLMProviderPoolSection from "./LLMProviderPoolSection";

describe("LLMProviderPoolSection", () => {
  it("renders provider pool heading", () => {
    render(
      <LLMProviderPoolSection
        values={{}}
        meta={{}}
        onChange={() => {}}
        t={
          {
            configSettings: { llmProviderPool: "Provider Pool" },
          } as any
        }
      />,
    );
    expect(screen.getByText("Provider Pool")).toBeTruthy();
  });
});
```

**Step 2**

```bash
cd knowledge-base-service/dashboard
pnpm test -- LLMProviderPoolSection.test.tsx
```

**预期输出:** 组件文件不存在导致 import 失败。

**Step 3:** 实现 `LLMProviderPoolSection`：编辑 JSON 文本区绑定 `values["llm.providers"]`，保存走既有 `useUpdateSettings` 批量 API。

**Step 4**

```bash
pnpm test -- LLMProviderPoolSection.test.tsx
```

**Step 5: Commit**

```bash
git add dashboard/src/components/settings/sections/LLMProviderPoolSection.tsx dashboard/src/components/settings/sections/LLMProviderPoolSection.test.tsx dashboard/src/components/settings/SystemConfigPanel.tsx
git commit -m "feat(dashboard): LLM provider pool editor section"
```

---

### Task 14 — Dashboard 策略 UI + 模型发现 API

**Files**

- **Create:** `dashboard/src/components/settings/sections/ModelStrategySection.tsx`
- **Modify:** `api/routes/provider_routes.py` — `GET /llm/providers/{name}/models`
- **Modify:** `llm/provider_factory.py` — `register_dynamic(name, cfg)` 与设计 §3.3.1 对齐
- **Create:** `tests/api/test_provider_models_route.py`

**Step 1: 后端测试示例**

```python
# tests/api/test_provider_models_route.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_list_models_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/llm/providers/gateway/models")
        assert r.status_code in (401, 403)
```

**Step 3:** 实现 `GET /llm/providers/{name}/models`：对 OpenAI 兼容 `GET {base_url}/models`（复用 provider 的 httpx client 或临时 AsyncClient）。

**Step 4**

```bash
uv run pytest tests/api/test_provider_models_route.py -v
cd dashboard && pnpm test -- ModelStrategySection
```

**Step 5: Commit**

```bash
git commit -am "feat(llm): provider model discovery API and strategy section"
```

---

## Sprint 3 — 搜索迁移（Task 15–20）

### Task 15 — `WikiAskService` 迁移到 `IterativeRAGEngine`

**Files**

- **Modify:** `wiki/ask.py`
- **Modify:** `config.py` — `AppWikiFlags.iterative_rag_enabled: bool = False`
- **Modify:** `tests/wiki/unit/test_ask.py`, `tests/wiki/unit/test_ask_v2.py`

**Step 1:** 新增测试：`use_iterative_rag=True` 时 `ask_stream` 发射与设计 §2.7 兼容的 v2 事件（保留现有 `token`/`sources`/`done`/`error`）。

**Step 3:** 在 `WikiAskService` 注入可选 `IterativeRAGEngine`；`WIKI__ITERATIVE_RAG_ENABLED` 控制路径。

**Step 4**

```bash
uv run pytest tests/wiki/unit/test_ask.py tests/wiki/unit/test_ask_v2.py -v
```

**Step 5: Commit**

```bash
git commit -am "feat(wiki-ask): optional IterativeRAGEngine-backed streaming"
```

---

### Task 16 — `DeepSearchEngine` 迁移

**Files**

- **Modify:** `query/deep_search.py`
- **Modify:** `tests/api/test_deep_search_stream.py`

**Step 1:** 断言 `search_stream` 在 flag 打开时产出新事件类型同时 **保留** `plan`/`progress`/`search_done`/`synthesis`.` `conclusion`（向前兼容映射一层）。

**Step 4**

```bash
uv run pytest tests/api/test_deep_search_stream.py -v
```

**Step 5: Commit**

```bash
git commit -am "feat(deep-search): delegate iterative loop to IterativeRAGEngine"
```

---

### Task 17 — `DeepResearchService` 迁移

**Files**

- **Modify:** `wiki/deep_research.py`
- **Modify:** `tests/`（新增 `tests/wiki/test_deep_research_iterative.py`）

**Step 1:** 综合步骤改为单次 `IterativeRAGEngine` + `WikiRetriever`（或 Composite）输出 LLM 合成。

**Step 4**

```bash
uv run pytest tests/wiki/test_deep_research_iterative.py -v
```

**Step 5: Commit**

```bash
git commit -am "feat(deep-research): LLM synthesis via iterative RAG"
```

---

### Task 18 — `AskPanel` 迭代过程 UI

**Files**

- **Modify:** `dashboard/src/components/wiki/AskPanel.tsx`
- **Modify:** `dashboard/src/hooks/useWikiAsk.ts`

**Step 1:** 扩展 `consumeWikiAskStreamSseV2` 处理 `thinking_start`/`draft`/`gaps`/`refining`。

**Step 3:** UI 按设计 §2.11 叠卡片；AbortController 对接用户停止。

**Step 4**

```bash
cd dashboard && pnpm test -- useWikiAsk
```

**Step 5: Commit**

```bash
git commit -am "feat(dashboard): wiki ask iterative RAG timeline UI"
```

---

### Task 19 — `DeepSearchSection` 适配

**Files**

- **Modify:** `dashboard/src/hooks/useDeepSearchStream.ts`
- **Modify:** `dashboard/src/components/DeepSearchSection.tsx`

**Step 1:** Vitest：新事件类型下 `conclusion` 仍能渲染。

**Step 4**

```bash
cd dashboard && pnpm test -- DeepSearchSection
```

**Step 5: Commit**

```bash
git commit -am "fix(dashboard): deep search stream handles unified RAG events"
```

---

### Task 20 — API 路由兼容

**Files**

- **Modify:** `api/routes/wiki_ask_routes.py` — `page_path` / `page_context` 查询参数
- **Modify:** `api/routes/wiki_shared.py` — 依赖注入 `ModelStrategy`（若需要）

**Step 1:** API 测试：旧客户端不传新参数行为不变。

**Step 4**

```bash
uv run pytest tests/api/ -k wiki_ask -v
```

**Step 5: Commit**

```bash
git commit -am "feat(api): wiki ask routes accept page_context for RAG scope"
```

---

## Sprint 4 — 增强（Task 21–26）

### Task 21 — T8 复杂度深化（`CompositionStrategy`）

**Files**

- **Modify:** `wiki/domain_complexity.py`
- **Modify:** `tests/wiki/test_domain_complexity_strategy.py`（新建）

**Step 1:** 断言 `ComplexityMetrics.recommended_strategy.model_task_type` 在 HIGH 为 `reasoning`。

**Step 4**

```bash
uv run pytest tests/wiki/test_domain_complexity_strategy.py -v
```

**Step 5: Commit**

```bash
git commit -am "feat(wiki): composition strategy from domain complexity metrics"
```

---

### Task 22 — 复杂度 ↔ `ModelStrategy` 联动

**Files**

- **Modify:** `wiki/model_strategy.py` — `resolve(..., complexity_metrics=None)`
- **Modify:** `wiki/pipeline_nodes.py` — 传递 `ComplexityMetrics`

**Step 4**

```bash
uv run pytest tests/wiki/test_model_strategy.py -v
```

**Step 5: Commit**

```bash
git commit -am "feat(llm): ModelStrategy honors complexity when DB unset"
```

---

### Task 23 — C4 `code_structure` 语义分组

**Files**

- **Modify:** `wiki/tree_linker.py`
- **Modify:** `config.py` — `code_structure_semantic_group` / `code_structure_semantic_group_threshold`
- **Modify:** `tests/wiki/test_tree_linker_semantic_groups.py`

**Step 1:** 给定 ≥8 页时调用 `WikiStructurePlanner._semantic_group_modules`（需从 planner 抽取可注入依赖以便测试 mock）。

**Step 4**

```bash
uv run pytest tests/wiki/test_tree_linker_semantic_groups.py -v
```

**Step 5: Commit**

```bash
git commit -am "feat(wiki): optional semantic grouping under code_structure sections"
```

---

### Task 24 — MCP A1 `page_context`

**Files**

- **Modify:** `wiki/mcp_tools.py` — `WIKI_MCP_TOOLS_MANIFEST` + handlers
- **Modify:** `wiki/kb_wiki_pipeline.py` 或 MCP server 绑定

**Step 4**

```bash
uv run pytest tests/ -k mcp -v
```

**Step 5: Commit**

```bash
git commit -am "feat(mcp): wiki_search page_context boost for linked pages"
```

---

### Task 25 — MCP A5 `unified_knowledge_query`

**Files**

- **Modify:** `wiki/mcp_tools.py`
- **Modify:** `docs/MCP-INTEGRATION.md`

**Step 4**

```bash
uv run pytest tests/ -k unified_knowledge -v
```

**Step 5: Commit**

```bash
git commit -am "feat(mcp): unified_knowledge_query tool"
```

---

### Task 26 — 集成测试

**Files**

- **Create:** `tests/wiki/integration/test_iterative_rag_end_to_end.py`

**Step 4**

```bash
uv run pytest tests/wiki/integration/test_iterative_rag_end_to_end.py -v
```

**Step 5: Commit**

```bash
git commit -am "test(wiki): iterative RAG integration coverage"
```

---

## Sprint 5 — 收尾（Task 27–30）

### Task 27 — E2E 测试

**Files**

- **Create或Modify:** `e2e/wiki-ask-iterative.spec.ts`（遵循现有 Playwright 配置）

**Step 2**

```bash
cd knowledge-base-service/dashboard
pnpm exec playwright test wiki-ask-iterative.spec.ts
```

**Step 5: Commit**

```bash
git commit -am "test(e2e): wiki ask iterative flow"
```

---

### Task 28 — 前端测试收口

**Step 4**

```bash
cd dashboard && pnpm test
```

**Step 5: Commit**

```bash
git commit -am "test(dashboard): cover RAG SSE UI hooks"
```

---

### Task 29 — 文档更新

**Files**

- **Modify:** `docs/ARCHITECTURE.md`
- **Modify:** `docs/MCP-INTEGRATION.md`

**Step 5: Commit**

```bash
git commit -m "docs: Phase 6 iterative RAG and model strategy"
```

---

### Task 30 — 分析报告更新

**Files**

- 按仓库惯例更新 `docs/superpowers/analysis/` 或 `DEEP_ANALYSIS` 对应文件，将 T7/T8/P3/C4/A1/A5 标为完成并链接本计划。

**Step 5: Commit**

```bash
git commit -m "docs: mark Phase 6 spec items complete in analysis report"
```

---

## Self-Review

### 1. Spec coverage（设计提案 section → Task）

| Spec | 对应 Task |
|------|-----------|
| §2 统一迭代 RAG（协议、Retriever、引擎、SSE、迁移） | 1–7, 15–20 |
| §3 动态模型策略（池、策略、热重载、ModelStrategy、UI、发现 API） | 8–14 |
| §4 T8 复杂度深化 | 21–22 |
| §5 C4 语义分组 | 23 |
| §6 MCP A1/A5 | 24–25 |
| §7 实施计划 Sprint 1–5 | 本文件整表 |
| §8 迁移/回滚（feature flag） | 15–17（`iterative_rag_enabled` 等） |
| §9 风险 | Task 26–28（兼容与 E2E） |

### 2. Placeholder scan

- 本计划在 **Task 5** 明确需与 **Task 6** 同批落地 `rag_sse_append`，避免悬空引用。
- 全文未使用 `TBD` / `TODO` / `implement later` 作为交付物占位；**Task 11/12** 的测试文件名在仓库中若已存在同类测试，应合并而非重复。

### 3. Type consistency

| 概念 | 统一约定 |
|------|----------|
| LLM 消息接口 | 管道与 `WikiAskService` 历史代码多用 `complete(messages)`；`wiki.context.LLMPort` 使用 `generate`。`ModelStrategy.get_llm_port` 返回 **`wiki.context.LLMPort`**（供 composer），RAG 引擎内部可用 `complete` provider 或单独 `RAGLLMPort` Protocol，但 **避免同名 `LLMPort` 混用**：在 `wiki/ask.py` 保留原有 `runtime_checkable` LLMPort，新增 `RAGChatLLMPort` 若需。 |
| SSE 事件 | 对外 JSON 键名 `type`；轮次键 **`round`**（number），与前端 `useWikiAsk` 解析一致。 |
| 配置键 | DB key **`llm.providers`**；策略键 **`llm.strategy.<task_type>`**；与环境变量优先级见设计 §3.3（实现落在 `SettingsService` merge 层）。 |
| `LLMPortBridge.generate` kwargs | Task 8 的 `_LLMPortWithDefault` 若传 `extra_params` 与实际 `LLMPortBridge` 不一致，**以 `llm/base_provider.py` 为准** 调整（推荐扩展 `generate(..., reasoning_effort: str | None = None)` 并透传 `extra_params`）。 |

---

**本计划已写入:** `knowledge-base-service/docs/superpowers/plans/2026-05-01-phase6-iterative-rag-and-model-strategy.md`
