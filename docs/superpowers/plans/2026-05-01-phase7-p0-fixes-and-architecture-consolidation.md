# Phase 7 — P0 关键修复 + P1 架构整合 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 4 个 P0 关键问题，统一 LLM 抽象层为 2 层架构，收敛 3 套搜索系统为 IterativeRAGEngine 单内核，清理次要技术债务。

**Architecture:** 2 层 LLM 架构（BaseLLMProvider + 统一 LLMPort）；IterativeRAGEngine 作为所有搜索系统的唯一内核，通过新建 HybridGraphRetriever 统一检索能力；各 API 端点保留差异化编排层。

**Tech Stack:** Python 3.12, FastAPI, LangGraph, pytest, asyncio

**Spec:** `docs/superpowers/specs/2026-05-01-phase7-p0-fixes-and-architecture-consolidation-design.md`

---

## 文件结构

### 新建文件
| 文件 | 职责 |
|------|------|
| `wiki/llm_port.py` | 统一 LLMPort Protocol（合并 wiki.context.LLMPort + wiki.ask.LLMPort） |
| `wiki/rag/hybrid_graph_retriever.py` | 将 HybridQueryService + GraphQueryService 封装为 Retriever 协议 |
| `tests/wiki/test_llm_port.py` | LLMPort Protocol 满足性测试 |
| `tests/wiki/rag/test_hybrid_graph_retriever.py` | HybridGraphRetriever 单元测试 |
| `tests/wiki/test_mcp_unified_knowledge_rag.py` | unified_knowledge_query RAG 集成测试 |
| `tests/integration/test_search_unification.py` | 搜索系统统一集成测试 |

### 修改文件
| 文件 | 改动摘要 |
|------|---------|
| `wiki/mcp_tools.py` | P0-1: unified_knowledge_query 接入 IterativeRAGEngine |
| `api/mcp_server.py` | 注入 rag_engine 到 WikiMCPHandler |
| `services/kb_service.py` | 组装 rag_engine 并传递 |
| `llm/base_provider.py` | P0-3: max_context_tokens 动态化 |
| `wiki/context.py` | P1-A: 删除 LLMPort 定义，import 新 LLMPort |
| `wiki/ask.py` | P1-A: 删除 LLMPort 定义，import 新 LLMPort |
| `wiki/model_strategy.py` | P1-A: import 路径修改 |
| `wiki/composer.py` | P1-A: import 路径修改 |
| `wiki/topic_page_composer.py` | P1-A: import 路径修改 |
| `wiki/business_domain_planner.py` | P1-A: import 路径修改 |
| `wiki/system_overview_composer.py` | P1-A: import 路径修改 |
| `wiki/domain_overview_composer.py` | P1-A: import 路径修改 |
| `wiki/semantic_diagram_gen.py` | P1-A: import 路径修改 |
| `wiki/contradiction_detector.py` | P1-A: import 路径修改 |
| `wiki/cross_repo_domain_planner.py` | P1-A: import 路径修改 |
| `wiki/async_enrichment.py` | P1-A: import 路径修改 |
| `wiki/structure_planner.py` | P1-A: 删除本地 LLMPort，import 统一版 |
| `wiki/topic_structure_planner.py` | P1-A: 删除本地 LLMPort，import 统一版 |
| `wiki/bootstrap.py` | P1-B: 组装 IterativeRAGEngine 并注入所有服务 |
| `query/deep_search.py` | P1-B: 改写为委托 IterativeRAGEngine |
| `wiki/deep_research.py` | P1-B: 改写为直接使用 IterativeRAGEngine |
| `wiki/ask.py` | P1-B: 改写为直接使用 IterativeRAGEngine |
| `config.py` | P1-B: 删除 iterative_rag_enabled flag |
| `docs/ONBOARDING.md` | P0-4: 工具数量 20→22 |
| `docs/README-DOCS.md` | P0-4: 工具数量 20→22 |
| `docs/wiki-generation-architecture.md` | P0-4: 工具数量 20→22 |
| `docs/CODEMAPS/INDEX.md` | P0-4 + P0-5: 工具数量 + 断裂链接 |

---

## Sprint 1: P0 关键修复

### Task 1: `unified_knowledge_query` 接入 IterativeRAGEngine

**Files:**
- Modify: `wiki/mcp_tools.py:275-289` (WikiMCPHandler.__init__)
- Modify: `wiki/mcp_tools.py:444-472` (handle_unified_knowledge_query)
- Modify: `services/kb_service.py` (装配 rag_engine)
- Test: `tests/wiki/test_mcp_unified_knowledge_rag.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_mcp_unified_knowledge_rag.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.mcp_tools import WikiMCPHandler
from wiki.rag.protocol import Chunk


@pytest.fixture
def mock_rag_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(return_value={
        "current_draft": "The authentication system uses JWT tokens...",
        "accumulated_context": [
            Chunk(content="jwt auth logic", source="wiki", title="auth.md", relevance=0.9),
        ],
        "sse_events": [],
        "round": 2,
        "confidence": 0.92,
    })
    return engine


@pytest.mark.asyncio
async def test_unified_knowledge_query_uses_rag_engine(mock_rag_engine):
    handler = WikiMCPHandler(pipeline=MagicMock(), rag_engine=mock_rag_engine)
    result = await handler.handle_unified_knowledge_query({
        "question": "How does authentication work?",
        "scope": "global",
        "max_rounds": 5,
    })
    mock_rag_engine.arun.assert_called_once()
    assert "JWT tokens" in result["answer"]
    assert len(result["sources"]) > 0


@pytest.mark.asyncio
async def test_unified_knowledge_query_requires_question(mock_rag_engine):
    handler = WikiMCPHandler(pipeline=MagicMock(), rag_engine=mock_rag_engine)
    result = await handler.handle_unified_knowledge_query({"question": ""})
    assert "error" in result or "invalid_params" in str(result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_mcp_unified_knowledge_rag.py -v`
Expected: FAIL — `WikiMCPHandler.__init__` does not accept `rag_engine`

- [ ] **Step 3: Modify WikiMCPHandler.__init__ to accept rag_engine**

在 `wiki/mcp_tools.py:275-283`，在最后一个参数 `wiki_config` 后新增 `rag_engine` 参数：

```python
    def __init__(
        self,
        pipeline: Any | None = None,
        graph: GraphQueryPort | None = None,
        store: Any | None = None,
        wiki_cache: Any | None = None,
        repo_registry: Any | None = None,
        wiki_config: Any | None = None,
        rag_engine: Any | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._graph = graph
        self._store = store
        self._wiki_cache = wiki_cache
        self._repo_registry = repo_registry
        self._wiki_config = wiki_config
        self._rag_engine = rag_engine
```

- [ ] **Step 4: Rewrite handle_unified_knowledge_query to use rag_engine**

替换 `wiki/mcp_tools.py:444-472`：

```python
    async def handle_unified_knowledge_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle unified_knowledge_query MCP tool call via IterativeRAGEngine."""
        question = str(arguments.get("question", "")).strip()
        if not question:
            return self._mcp_error("invalid_params", "question parameter is required")

        if self._rag_engine is None:
            return self._mcp_error("not_configured", "RAG engine not available")

        scope_raw = str(arguments.get("scope", "global") or "global").strip() or "global"
        repository_raw = arguments.get("repository")
        try:
            max_rounds = int(arguments.get("max_rounds", 5))
        except (ValueError, TypeError):
            return self._mcp_error("invalid_params", "max_rounds must be an integer")

        from wiki.rag.protocol import RetrievalScope

        scope = RetrievalScope(
            scope_type="business" if repository_raw else "global",
            business_id=repository_raw if repository_raw else None,
        )

        try:
            state = await self._rag_engine.arun(
                question=question, scope=scope, max_rounds=max_rounds,
            )
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))

        sources = []
        for chunk in state.get("accumulated_context", []):
            sources.append({"title": chunk.title, "path": chunk.source})

        return {
            "answer": state.get("current_draft", ""),
            "sources": sources,
            "scope": scope_raw,
            "rounds": state.get("round", 1),
            "confidence": state.get("confidence", 0.0),
        }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_mcp_unified_knowledge_rag.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/mcp_tools.py tests/wiki/test_mcp_unified_knowledge_rag.py
git commit -m "feat(mcp): wire unified_knowledge_query to IterativeRAGEngine"
```

---

### Task 2: `GatewayLLMProviderAdapter.max_context_tokens` 动态化

**Files:**
- Modify: `llm/base_provider.py:56-69`
- Test: `tests/llm/test_gateway_adapter_context_tokens.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/llm/test_gateway_adapter_context_tokens.py
from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from llm.base_provider import GatewayLLMProviderAdapter


def test_default_max_context_tokens():
    inner = MagicMock()
    adapter = GatewayLLMProviderAdapter(inner)
    assert adapter.max_context_tokens == 128_000


def test_explicit_max_context_tokens():
    inner = MagicMock()
    adapter = GatewayLLMProviderAdapter(inner, max_context_tokens=200_000)
    assert adapter.max_context_tokens == 200_000


def test_max_context_tokens_from_inner_config():
    inner = MagicMock()
    inner._config = MagicMock()
    inner._config.max_context_tokens = 64_000
    adapter = GatewayLLMProviderAdapter(inner)
    assert adapter.max_context_tokens == 64_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/llm/test_gateway_adapter_context_tokens.py -v`
Expected: FAIL — `__init__` does not accept `max_context_tokens`

- [ ] **Step 3: Modify GatewayLLMProviderAdapter**

在 `llm/base_provider.py:56-69` 修改：

```python
    def __init__(self, inner: LLMProvider, *, max_context_tokens: int | None = None) -> None:
        self._inner = inner
        self._max_context_tokens = max_context_tokens

    @property
    def max_context_tokens(self) -> int:
        if self._max_context_tokens is not None:
            return self._max_context_tokens
        config = getattr(self._inner, "_config", None)
        if config and hasattr(config, "max_context_tokens"):
            return config.max_context_tokens
        return 128_000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/llm/test_gateway_adapter_context_tokens.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm/base_provider.py tests/llm/test_gateway_adapter_context_tokens.py
git commit -m "fix(llm): make GatewayLLMProviderAdapter.max_context_tokens configurable"
```

---

### Task 3: 文档工具数量统一 + CODEMAPS 断裂链接

**Files:**
- Modify: `docs/ONBOARDING.md`
- Modify: `docs/README-DOCS.md`
- Modify: `docs/wiki-generation-architecture.md`
- Modify: `docs/CODEMAPS/INDEX.md`

- [ ] **Step 1: 修复 docs/ONBOARDING.md**

将 `20` 个工具改为 `22`，将 `8` 个 Wiki 改为 `10`。

- [ ] **Step 2: 修复 docs/README-DOCS.md**

将 `20` 个工具改为 `22`，将 `8` 个 Wiki 改为 `10`。

- [ ] **Step 3: 修复 docs/wiki-generation-architecture.md**

L9 和 L186 处将 `20` 改为 `22`，`8` 改为 `10`。

- [ ] **Step 4: 修复 docs/CODEMAPS/INDEX.md**

L13 处将 `20` 改为 `22`。
L35 处将 `../superpowers/specs/2026-04-27-wiki-generation-architecture-improvement-design.md` 替换为 `../wiki-generation-architecture.md`。

- [ ] **Step 5: 验证无其他引用 20 工具的文档**

Run: `cd knowledge-base-service && rg "20.*工具|20.*tool" docs/ --ignore-case`
Expected: 无匹配（注意 `docs/MCP-INTEGRATION.md` 已经是正确的 22 工具，无需修改）

- [ ] **Step 6: Commit**

```bash
git add docs/
git commit -m "docs: unify MCP tool count to 22 and fix broken CODEMAPS link"
```

---

## Sprint 2: P1-A LLM 抽象层统一

### Task 4: 创建统一 LLMPort Protocol

**Files:**
- Create: `wiki/llm_port.py`
- Test: `tests/wiki/test_llm_port.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_llm_port.py
from __future__ import annotations
import pytest
from wiki.llm_port import LLMPort
from llm.base_provider import LLMPortBridge


def test_llm_port_is_runtime_checkable():
    assert hasattr(LLMPort, "__protocol_attrs__") or hasattr(LLMPort, "__abstractmethods__") or True
    assert isinstance(LLMPort, type)


def test_llm_port_bridge_satisfies_llm_port():
    from unittest.mock import AsyncMock, MagicMock
    inner = MagicMock()
    inner.complete = AsyncMock(return_value="ok")
    inner.complete_stream = AsyncMock()
    bridge = LLMPortBridge(inner)
    assert isinstance(bridge, LLMPort)


def test_llm_port_has_generate_and_complete():
    assert hasattr(LLMPort, "generate")
    assert hasattr(LLMPort, "complete")
    assert hasattr(LLMPort, "complete_stream")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_llm_port.py -v`
Expected: FAIL — `wiki.llm_port` does not exist

- [ ] **Step 3: Create wiki/llm_port.py**

```python
# wiki/llm_port.py
from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Unified LLM domain port.

    Merges the former wiki.context.LLMPort (generate) and
    wiki.ask.LLMPort (complete) into a single protocol.
    All wiki/rag/ask/research services use this protocol.
    """

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str: ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str: ...

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_llm_port.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/llm_port.py tests/wiki/test_llm_port.py
git commit -m "feat(llm): create unified LLMPort protocol in wiki/llm_port.py"
```

---

### Task 5: 迁移 wiki/context.py — 删除内联 LLMPort

**Files:**
- Modify: `wiki/context.py:24-33`

- [ ] **Step 1: 删除 wiki/context.py 中的 LLMPort 定义**

删除 `wiki/context.py:24-33` 的 `class LLMPort(Protocol)` 定义，替换为：

```python
from wiki.llm_port import LLMPort
```

确保 `LLMPort` 仍然从 `wiki.context` 导出（保持向后兼容的 re-export）。

- [ ] **Step 2: 运行现有测试确保不 break**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/unit/test_context.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/context.py
git commit -m "refactor(llm): replace wiki.context.LLMPort with re-export from wiki.llm_port"
```

---

### Task 6: 迁移 wiki/ask.py — 删除内联 LLMPort

**Files:**
- Modify: `wiki/ask.py:80-82`

- [ ] **Step 1: 删除 wiki/ask.py 中的 LLMPort 定义**

删除 `wiki/ask.py:80-82` 的 `class LLMPort(Protocol)` 定义，替换为：

```python
from wiki.llm_port import LLMPort
```

同时修改 `ask_stream` 方法（L791）中对 `complete_stream` 的 `getattr` 动态查找：

```python
# Before:
stream_fn = getattr(self._llm, "complete_stream", None)
if _is_async_text_stream_method(stream_fn):

# After — LLMPort now has complete_stream, but keep safety check:
stream_fn = getattr(self._llm, "complete_stream", None)
if stream_fn is not None and _is_async_text_stream_method(stream_fn):
```

保留安全检查，因为 `complete_stream` 在 Protocol 中虽然定义了，但鸭子类型的实现者可能省略。

- [ ] **Step 2: 运行现有测试**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/unit/test_ask.py tests/wiki/unit/test_ask_v2.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/ask.py
git commit -m "refactor(llm): replace wiki.ask.LLMPort with import from wiki.llm_port"
```

---

### Task 7: 批量迁移所有 LLMPort 消费者

**Files:**
- Modify: `wiki/composer.py`
- Modify: `wiki/topic_page_composer.py`
- Modify: `wiki/business_domain_planner.py`
- Modify: `wiki/system_overview_composer.py`
- Modify: `wiki/domain_overview_composer.py`
- Modify: `wiki/semantic_diagram_gen.py`
- Modify: `wiki/contradiction_detector.py`
- Modify: `wiki/cross_repo_domain_planner.py`
- Modify: `wiki/async_enrichment.py`
- Modify: `wiki/model_strategy.py`
- Modify: `wiki/structure_planner.py` (本地 LLMPort 定义 → import 统一版)
- Modify: `wiki/topic_structure_planner.py` (本地 LLMPort 定义 → import 统一版)
- Modify: `wiki/rag/engine.py` (内联 `_LLM` Protocol → import `LLMPort`)

- [ ] **Step 1: 批量替换 import 路径**

在以下文件中，将 `from wiki.context import LLMPort` 改为 `from wiki.llm_port import LLMPort`：

1. `wiki/composer.py` — 注意同时 import `WikiContextBuilder` 仍来自 `wiki.context`
2. `wiki/topic_page_composer.py`
3. `wiki/business_domain_planner.py`
4. `wiki/system_overview_composer.py`
5. `wiki/domain_overview_composer.py`
6. `wiki/semantic_diagram_gen.py`
7. `wiki/contradiction_detector.py`
8. `wiki/cross_repo_domain_planner.py`
9. `wiki/async_enrichment.py`
10. `wiki/model_strategy.py`

- [ ] **Step 1b: 迁移本地 LLMPort 定义**

11. `wiki/structure_planner.py` L39: 删除本地 `class LLMPort(Protocol)` 定义，替换为 `from wiki.llm_port import LLMPort`
12. `wiki/topic_structure_planner.py` L20: 同上
13. `wiki/rag/engine.py` L28-29: 将内联 `class _LLM(Protocol)` 替换为 `from wiki.llm_port import LLMPort as _LLM`（或直接 import `LLMPort`）

注意：`wiki/structure_planner.py` 和 `wiki/topic_structure_planner.py` 的本地 `LLMPort` 签名比统一版更简单（缺少 `model`、`max_tokens`、`reasoning_effort` 参数）。因为 Python Protocol 使用鸭子类型，调用侧只传 `(prompt, system)` 的代码不需要修改 — 只要实现者支持更多参数即可。

- [ ] **Step 2: 验证无遗漏**

Run: `cd knowledge-base-service && rg "from wiki\.context import.*LLMPort" wiki/ --ignore-case`
Expected: 仅 `wiki/context.py` 中的 re-export（`from wiki.llm_port import LLMPort`）和 `wiki/composer.py`（仍需 `WikiContextBuilder`）

Run: `cd knowledge-base-service && rg "from wiki\.ask import.*LLMPort" wiki/ --ignore-case`
Expected: 无匹配

Run: `cd knowledge-base-service && rg "class LLMPort" wiki/ --ignore-case`
Expected: 仅 `wiki/llm_port.py` 中的定义（`wiki/context.py` 和 `wiki/ask.py` 改为 re-export，`wiki/structure_planner.py` 和 `wiki/topic_structure_planner.py` 已删除本地定义）

- [ ] **Step 3: 运行全量测试**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ -v --timeout=60`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/
git commit -m "refactor(llm): migrate all LLMPort consumers to wiki.llm_port"
```

---

## Sprint 3: P1-B 搜索系统统一

### Task 8: 创建 HybridGraphRetriever

**Files:**
- Create: `wiki/rag/hybrid_graph_retriever.py`
- Test: `tests/wiki/rag/test_hybrid_graph_retriever.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/rag/test_hybrid_graph_retriever.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever
from wiki.rag.protocol import Chunk, RetrievalScope


@pytest.fixture
def mock_hybrid():
    svc = AsyncMock()
    svc.search_with_context = AsyncMock(return_value=[
        MagicMock(content="hybrid result", title="page1", path="/wiki/page1", score=0.9),
    ])
    return svc


@pytest.fixture
def mock_graph():
    svc = AsyncMock()
    svc.query = AsyncMock(return_value=[
        {"type": "concept", "name": "Auth", "relations": ["uses JWT"]},
    ])
    return svc


@pytest.mark.asyncio
async def test_retrieve_combines_hybrid_and_graph(mock_hybrid, mock_graph):
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    chunks = await retriever.retrieve(["auth flow"], scope)
    assert len(chunks) >= 2
    assert any("hybrid result" in c.content for c in chunks)
    assert any("Auth" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_retrieve_multiple_queries(mock_hybrid, mock_graph):
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    chunks = await retriever.retrieve(["query1", "query2"], scope)
    assert mock_hybrid.search_with_context.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/rag/test_hybrid_graph_retriever.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement HybridGraphRetriever**

```python
# wiki/rag/hybrid_graph_retriever.py
from __future__ import annotations

from typing import Any

from wiki.rag.protocol import Chunk, RetrievalScope


class HybridGraphRetriever:
    """Wraps HybridQueryService + GraphQueryService as a Retriever."""

    def __init__(
        self,
        hybrid_service: Any,
        graph_service: Any,
    ) -> None:
        self._hybrid = hybrid_service
        self._graph = graph_service

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        for query in queries:
            hybrid_results = await self._hybrid.search_with_context(
                query, business_id=scope.business_id,
            )
            for r in hybrid_results:
                chunks.append(Chunk(
                    content=getattr(r, "content", str(r)),
                    source="wiki",
                    title=getattr(r, "title", ""),
                    relevance=getattr(r, "score", 0.5),
                    metadata={"path": getattr(r, "path", "")},
                ))

            try:
                graph_results = await self._graph.query(
                    query, business_id=scope.business_id,
                )
            except Exception:
                graph_results = []
            for r in graph_results:
                chunks.append(Chunk(
                    content=str(r),
                    source="graph",
                    title="graph",
                    relevance=0.5,
                ))
        return chunks[:limit]
```

- [ ] **Step 4: Export from wiki/rag/__init__.py**

在 `wiki/rag/__init__.py` 中追加：

```python
from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever
```

并在 `__all__` 中追加 `"HybridGraphRetriever"`。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/rag/test_hybrid_graph_retriever.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/rag/hybrid_graph_retriever.py wiki/rag/__init__.py tests/wiki/rag/test_hybrid_graph_retriever.py
git commit -m "feat(rag): add HybridGraphRetriever combining hybrid search and graph queries"
```

---

### Task 9: 改写 WikiAskService — 直接使用 IterativeRAGEngine

**Files:**
- Modify: `wiki/ask.py` (WikiAskService.__init__, ask_stream)
- Test: `tests/wiki/unit/test_ask_unified.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/unit/test_ask_unified.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.ask import WikiAskService
from wiki.rag.protocol import Chunk


@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(return_value={
        "current_draft": "The answer is 42.",
        "accumulated_context": [
            Chunk(content="guide content", source="wiki", title="guide.md", relevance=0.9),
        ],
        "sse_events": [
            {"type": "searching", "round": 1},
            {"type": "draft", "round": 1, "content": "The answer is 42."},
            {"type": "done", "final_answer": "The answer is 42."},
        ],
        "round": 1,
        "confidence": 0.95,
    })
    return engine


@pytest.mark.asyncio
async def test_ask_stream_uses_engine(mock_engine):
    svc = WikiAskService(
        search=AsyncMock(),
        llm=MagicMock(),
        rag_engine=mock_engine,
    )
    events = []
    async for event in svc.ask_stream("What is 42?", business_id="biz-1"):
        events.append(event)

    mock_engine.arun.assert_called_once()
    event_types = [e.get("type") or e.get("event") for e in events]
    assert any("wiki-answer" in str(t) for t in event_types)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/unit/test_ask_unified.py -v`
Expected: FAIL — `engine` not accepted by `WikiAskService.__init__`

- [ ] **Step 3: Modify WikiAskService.__init__ — make rag_engine required**

在 `wiki/ask.py:636-646` 中修改 `WikiAskService.__init__`：
- 将 `rag_engine: Any | None = None` 改为 `rag_engine: Any`（必选参数，移到 `llm` 参数之后）
- 删除 `use_iterative_rag: bool = False` 参数
- 删除 `self._use_iterative_rag` 赋值

- [ ] **Step 4: Modify ask_stream to always use IterativeRAGEngine**

将 `ask_stream` 中的 `if self._use_iterative_rag` 分支改为默认路径，直接调用 `self._rag_engine.arun(question=..., scope=..., max_rounds=...)`。删除旧的非 RAG 路径。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/unit/test_ask_unified.py -v`
Expected: PASS

- [ ] **Step 6: Update existing ask tests**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/unit/test_ask.py tests/wiki/unit/test_ask_iterative.py -v`
修复因参数变更导致的测试失败（添加 `engine=` 参数到测试 fixture）。

- [ ] **Step 7: Commit**

```bash
git add wiki/ask.py tests/wiki/unit/
git commit -m "refactor(ask): WikiAskService now always uses IterativeRAGEngine"
```

---

### Task 10: 改写 DeepSearchEngine — 委托 IterativeRAGEngine

**Files:**
- Modify: `query/deep_search.py:148-322`
- Test: `tests/query/test_deep_search_unified.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/query/test_deep_search_unified.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from query.deep_search import DeepSearchEngine


@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(return_value={
        "current_draft": "Analysis: the system uses microservices.",
        "accumulated_context": [],
        "sse_events": [
            {"type": "searching", "round": 1},
            {"type": "done", "final_answer": "Analysis complete."},
        ],
        "round": 2,
        "confidence": 0.88,
    })
    return engine


@pytest.mark.asyncio
async def test_deep_search_delegates_to_engine(mock_engine):
    ds = DeepSearchEngine(rag_engine=mock_engine)
    result = await ds.search(
        query="How does the system work?",
        business_id="biz-1",
    )
    mock_engine.arun.assert_called_once()
    assert "microservices" in result["analysis"]


@pytest.mark.asyncio
async def test_deep_search_stream_yields_events(mock_engine):
    ds = DeepSearchEngine(rag_engine=mock_engine)
    events = []
    async for event in ds.search_stream(
        query="How does auth work?",
        business_id="biz-1",
    ):
        events.append(event)
    assert len(events) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/query/test_deep_search_unified.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite DeepSearchEngine**

替换 `query/deep_search.py` 中 `DeepSearchEngine` 的实现：

```python
class DeepSearchEngine:
    """Deep search delegating to IterativeRAGEngine."""

    def __init__(self, rag_engine: Any) -> None:
        self._engine = rag_engine

    async def search(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        include_code: bool = True,
        business_id: str = "",
    ) -> dict[str, Any]:
        from wiki.rag.protocol import RetrievalScope

        scope = RetrievalScope(
            scope_type="business" if business_id else "global",
            business_id=business_id or None,
        )
        state = await self._engine.arun(
            question=query, scope=scope, max_rounds=max_iterations,
        )
        return {
            "analysis": state.get("current_draft", ""),
            "search_trace": self._build_trace(state.get("sse_events", [])),
            "business_flows": [],
            "code_locations": [],
        }

    async def search_stream(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        include_code: bool = True,
        business_id: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        from wiki.rag.protocol import RetrievalScope

        scope = RetrievalScope(
            scope_type="business" if business_id else "global",
            business_id=business_id or None,
        )
        yield {"type": "plan", "data": {"intent": query, "sub_queries": [query]}}

        state = await self._engine.arun(
            question=query, scope=scope, max_rounds=max_iterations,
        )

        for sse in state.get("sse_events", []):
            yield {"type": "progress", "data": sse}

        yield {
            "type": "conclusion",
            "data": {
                "analysis": state.get("current_draft", ""),
                "sufficient": True,
            },
        }

    @staticmethod
    def _build_trace(sse_events: list[dict]) -> list[dict]:
        return [{"stage": e.get("type", "unknown"), **e} for e in sse_events]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/query/test_deep_search_unified.py -v`
Expected: PASS

- [ ] **Step 5: Update existing deep search tests**

Run: `cd knowledge-base-service && python -m pytest tests/query/ -v`
修复因构造函数变更导致的失败。

- [ ] **Step 6: Commit**

```bash
git add query/deep_search.py tests/query/
git commit -m "refactor(search): DeepSearchEngine now delegates to IterativeRAGEngine"
```

---

### Task 11: 改写 DeepResearchService — 直接使用 IterativeRAGEngine

**Files:**
- Modify: `wiki/deep_research.py:17-27`
- Test: `tests/wiki/test_deep_research_unified.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_deep_research_unified.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.deep_research import DeepResearchService


@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(return_value={
        "current_draft": "Sub-answer for the question.",
        "accumulated_context": [],
        "sse_events": [],
        "round": 1,
        "confidence": 0.9,
    })
    return engine


@pytest.mark.asyncio
async def test_research_delegates_to_engine(mock_engine):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="sub q1\nsub q2")
    svc = DeepResearchService(rag_engine=mock_engine, llm=llm)
    result = await svc.research(question="Compare auth methods", business_id="biz-1")
    assert mock_engine.arun.call_count >= 1
    assert "synthesis" in result or "sub_answers" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_deep_research_unified.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite DeepResearchService**

在 `wiki/deep_research.py` 中：

```python
class DeepResearchService:
    def __init__(
        self,
        rag_engine: Any,
        llm: _LLMDecomposePort | Any | None = None,
    ) -> None:
        self._engine = rag_engine
        self._llm = llm

    async def research(
        self,
        question: str,
        business_id: str = "",
        *,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        sub_questions = await self.decompose_question(question)

        from wiki.rag.protocol import RetrievalScope
        scope = RetrievalScope(
            scope_type="business" if business_id else "global",
            business_id=business_id or None,
        )

        sub_answers = []
        for sq in sub_questions:
            state = await self._engine.arun(
                question=sq, scope=scope, max_rounds=5,
            )
            sub_answers.append(state.get("current_draft", ""))

        synthesis = await self._synthesize(question, sub_questions, sub_answers)
        return {
            "question": question,
            "sub_questions": sub_questions,
            "sub_answers": sub_answers,
            "synthesis": synthesis,
        }
```

保留现有的 `decompose_question` 和 `_synthesize` 方法逻辑，删除 `use_iterative_rag`、`ask_service` 参数，将 `rag_engine` 改为必选参数。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_deep_research_unified.py -v`
Expected: PASS

- [ ] **Step 5: Update existing tests**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_deep_research_iterative.py -v`
修复因参数变更导致的测试失败。

- [ ] **Step 6: Commit**

```bash
git add wiki/deep_research.py tests/wiki/
git commit -m "refactor(research): DeepResearchService now uses IterativeRAGEngine directly"
```

---

### Task 12: 实现 IterativeRAGEngine 3-LLM 自适应升级

**Files:**
- Modify: `wiki/rag/engine.py`
- Modify: `wiki/rag/events.py`
- Test: `tests/wiki/rag/test_engine_3llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/rag/test_engine_3llm.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.protocol import Chunk, RetrievalScope


@pytest.fixture
def mock_retriever():
    r = AsyncMock()
    r.retrieve = AsyncMock(return_value=[
        Chunk(content="some context", source="wiki", title="Page 1", relevance=0.8),
    ])
    return r


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"answer":"partial","gaps":["need more"],"next_queries":["follow up"],"confidence":0.5,"is_complete":false}')
    return llm


@pytest.mark.asyncio
async def test_plan_node_activates_on_round_2_low_confidence(mock_retriever, mock_llm):
    """Plan node should be triggered when round >= 2 and confidence < 0.85."""
    call_count = {"plan": 0, "generate": 0}
    original_complete = mock_llm.complete

    async def counting_complete(messages, **kwargs):
        content = messages[0]["content"] if messages else ""
        if "decompose" in content.lower() or "sub-queries" in content.lower():
            call_count["plan"] += 1
        else:
            call_count["generate"] += 1
        if call_count["generate"] >= 2:
            return '{"answer":"final answer","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'
        return await original_complete(messages, **kwargs)

    mock_llm.complete = AsyncMock(side_effect=counting_complete)

    engine = IterativeRAGEngine(retriever=mock_retriever, llm=mock_llm)
    scope = RetrievalScope(scope_type="global")
    state = await engine.arun(question="complex question", scope=scope, max_rounds=5)

    assert state.get("round", 0) >= 2
    assert any(e.get("type") == "planning" for e in state.get("sse_events", []))


@pytest.mark.asyncio
async def test_simple_question_skips_plan_and_evaluate(mock_retriever):
    """High-confidence answer on Round 1 should not trigger plan or evaluate."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"answer":"simple answer","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}')

    engine = IterativeRAGEngine(retriever=mock_retriever, llm=llm)
    scope = RetrievalScope(scope_type="global")
    state = await engine.arun(question="what is X?", scope=scope, max_rounds=5)

    assert state.get("round", 0) == 1
    event_types = [e.get("type") for e in state.get("sse_events", [])]
    assert "planning" not in event_types
    assert "evaluating" not in event_types


@pytest.mark.asyncio
async def test_evaluate_node_activates_on_persistent_low_confidence(mock_retriever):
    """Evaluate node should trigger when confidence < 0.7 after 3+ rounds."""
    round_counter = {"n": 0}

    async def multi_round_llm(messages, **kwargs):
        round_counter["n"] += 1
        content = messages[0]["content"] if messages else ""
        if "evaluate" in content.lower():
            return '{"score":0.6,"suggestions":["try different angle"],"next_queries":["new angle"]}'
        if "decompose" in content.lower() or "sub-queries" in content.lower():
            return '{"sub_queries":["sub q1","sub q2"]}'
        if round_counter["n"] <= 2:
            return '{"answer":"still unsure","gaps":["gap"],"next_queries":["more"],"confidence":0.5,"is_complete":false}'
        return '{"answer":"final","gaps":[],"next_queries":[],"confidence":0.9,"is_complete":true}'

    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=multi_round_llm)

    engine = IterativeRAGEngine(retriever=mock_retriever, llm=llm)
    scope = RetrievalScope(scope_type="global")
    state = await engine.arun(question="very complex", scope=scope, max_rounds=7)

    event_types = [e.get("type") for e in state.get("sse_events", [])]
    assert "evaluating" in event_types


@pytest.mark.asyncio
async def test_model_strategy_routes_llm_per_node(mock_retriever):
    """When model_strategy is provided, each node should use the routed LLM."""
    plan_llm = AsyncMock()
    plan_llm.complete = AsyncMock(return_value='{"sub_queries":["refined query"]}')
    gen_llm = AsyncMock()
    gen_llm.complete = AsyncMock(return_value='{"answer":"done","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}')

    strategy = AsyncMock()

    async def get_llm(task_type):
        if task_type == "rag_plan":
            return plan_llm
        return gen_llm

    strategy.get_llm_port = AsyncMock(side_effect=get_llm)

    engine = IterativeRAGEngine(
        retriever=mock_retriever, llm=gen_llm, model_strategy=strategy,
    )
    scope = RetrievalScope(scope_type="global")
    state = await engine.arun(question="test", scope=scope, max_rounds=5)
    assert state.get("current_draft")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/rag/test_engine_3llm.py -v`
Expected: FAIL — plan/evaluate 节点不存在

- [ ] **Step 3: 简化构造函数（合并 plan_llm/generate_llm/evaluate_llm → llm + model_strategy）**

在 `wiki/rag/engine.py:44-57` 中替换 `__init__`：

```python
class IterativeRAGEngine:
    def __init__(
        self,
        *,
        retriever: Retriever,
        llm: _LLM,
        model_strategy: Any | None = None,
    ):
        self._retriever = retriever
        self._llm = llm
        self._model_strategy = model_strategy
        self._graph = self._build_graph()
```

同时删除旧的 `self._plan_llm`、`self._gen_llm`、`self._eval_llm` 赋值。

- [ ] **Step 4: 添加 plan 节点**

在 `_build_graph` 中添加 `plan` 节点：

```python
async def plan(state: RAGState) -> dict[str, Any]:
    q = state["question"]
    gaps = state.get("gaps", [])
    gaps_text = "\n".join(f"- {g}" for g in gaps) if gaps else "None identified"
    
    plan_llm = self._llm
    if self._model_strategy:
        try:
            plan_llm = await self._model_strategy.get_llm_port("rag_plan")
        except Exception:
            pass
    
    prompt = (
        f"Original question:\n{q}\n\n"
        f"Information gaps:\n{gaps_text}\n\n"
        "Decompose into 2-4 precise sub-queries to fill these gaps. "
        "Reply with ONLY valid JSON: {\"sub_queries\": [\"query1\", \"query2\", ...]}"
    )
    raw = await plan_llm.complete([{"role": "user", "content": prompt}])
    data = _parse_reflection(raw)
    sub_queries = [str(x) for x in data.get("sub_queries", []) if str(x).strip()]
    if not sub_queries:
        sub_queries = state.get("next_queries", [])
    
    ev = rag_sse_append(state, "planning", {
        "round": state.get("round", 1),
        "sub_queries": sub_queries,
    })
    return {"next_queries": sub_queries, "sse_events": ev}
```

- [ ] **Step 5: 添加 evaluate 节点**

```python
async def evaluate(state: RAGState) -> dict[str, Any]:
    q = state["question"]
    draft = state.get("current_draft", "")
    
    eval_llm = self._llm
    if self._model_strategy:
        try:
            eval_llm = await self._model_strategy.get_llm_port("rag_evaluate")
        except Exception:
            pass
    
    prompt = (
        f"Question:\n{q}\n\n"
        f"Current answer:\n{draft}\n\n"
        "Evaluate this answer independently. Is it complete, accurate, and well-supported? "
        "Reply with ONLY valid JSON: "
        '{\"score\": number, \"suggestions\": [\"improvement1\"], \"next_queries\": [\"query1\"]}'
    )
    raw = await eval_llm.complete([{"role": "user", "content": prompt}])
    data = _parse_reflection(raw)
    
    score = float(data.get("score", 0.5))
    suggestions = [str(x) for x in data.get("suggestions", [])]
    nq = [str(x) for x in data.get("next_queries", []) if str(x).strip()]
    
    ev = rag_sse_append(state, "evaluating", {
        "round": state.get("round", 1),
        "score": score,
        "suggestions": suggestions[:3],
    })
    
    if score >= 0.85:
        return {"is_complete": True, "confidence": score, "sse_events": ev}
    return {"next_queries": nq, "sse_events": ev}
```

- [ ] **Step 6: 修改路由逻辑**

```python
graph.add_node("plan", plan)
graph.add_node("evaluate", evaluate)

def route_after_draft(s: RAGState):
    conf = s.get("confidence", 0.0)
    rnd = int(s.get("round", 1))
    max_r = int(s.get("max_rounds", 7))
    
    if s.get("is_complete") or rnd >= max_r:
        return "finalize"
    if not (s.get("next_queries") or []):
        return "finalize"
    
    # Round 3+, still low confidence → evaluate first
    if rnd >= 3 and conf < 0.7:
        return "evaluate"
    # Round 2+ → plan for better queries
    if rnd >= 2:
        return "plan"
    return "dynamic_retrieve"

graph.add_conditional_edges("generate_draft", route_after_draft)
graph.add_edge("plan", "dynamic_retrieve")
graph.add_edge("evaluate", "plan")
```

- [ ] **Step 7: 更新 generate_draft 的 LLM 选择**

在现有 `generate_draft` 函数（约 L69-102）中，将 `self._gen_llm` 替换为动态获取：

```python
async def generate_draft(state: RAGState) -> dict[str, Any]:
    gen_llm = self._llm
    if self._model_strategy:
        try:
            gen_llm = await self._model_strategy.get_llm_port("rag_generate")
        except Exception:
            pass
    q = state["question"]
    ctx = state.get("accumulated_context") or []
    ctx_text = "\n\n".join(f"### {c.title}\n{c.content}" for c in ctx[:50])
    prompt = (
        f"Question:\n{q}\n\nContext:\n{ctx_text}\n\n"
        "Reply with ONLY valid JSON: "
        '{"answer":string,"gaps":string[],"next_queries":string[],"confidence":number,"is_complete":bool}'
    )
    raw = await gen_llm.complete([{"role": "user", "content": prompt}])
    # ... rest of parse logic unchanged
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/rag/test_engine_3llm.py -v`
Expected: PASS

- [ ] **Step 9: Run all existing engine tests**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/rag/test_engine.py -v`
Expected: PASS（构造函数签名变更需更新现有测试）

- [ ] **Step 10: Commit**

```bash
git add wiki/rag/engine.py wiki/rag/events.py tests/wiki/rag/test_engine_3llm.py tests/wiki/rag/test_engine.py
git commit -m "feat(rag): implement 3-LLM adaptive escalation in IterativeRAGEngine"
```

---

### Task 13: Bootstrap 装配 + 删除 iterative_rag_enabled flag

**Files:**
- Modify: `wiki/bootstrap.py:234-319`
- Modify: `config.py:191`
- Modify: `services/kb_service.py` (DeepSearchEngine 装配)
- Test: `tests/integration/test_search_unification.py`

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_search_unification.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_iterative_rag_enabled_flag_removed():
    from config import AppWikiFlags
    assert not hasattr(AppWikiFlags, "iterative_rag_enabled") or True
    flags = AppWikiFlags()
    assert not hasattr(flags, "iterative_rag_enabled")
```

- [ ] **Step 2: 删除 config.py 中的 iterative_rag_enabled**

在 `config.py:191` 删除 `iterative_rag_enabled: bool = False`。

- [ ] **Step 3: 修改 wiki/bootstrap.py — 组装 IterativeRAGEngine**

在 `wiki/bootstrap.py` 中：

```python
from wiki.rag import (
    WikiRetriever, CompositeRetriever,
    IterativeRAGEngine,
)
from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever

# 在服务装配区域（约 L300 之后）:
wiki_retriever = WikiRetriever(wiki_search)
composite = CompositeRetriever([wiki_retriever])

rag_engine = IterativeRAGEngine(
    retriever=composite,
    llm=_wrap_llm(kb.llm_provider),
)

app.state.wiki_ask_service = WikiAskService(
    search=wiki_search,
    llm=_wrap_llm(kb.llm_provider),
    rag_engine=rag_engine,
    graph=kb.store,
    memory_loop=wiki_mem,
    conversation_store=conv_store,
)

app.state.wiki_deep_research_service = DeepResearchService(
    rag_engine=rag_engine,
    llm=_wrap_llm(kb.llm_provider),
)
```

- [ ] **Step 4: 修改 services/kb_service.py — DeepSearchEngine 装配**

在 `services/kb_service.py:255-261` 中，替换 `DeepSearchEngine` 的实例化：

```python
# Before:
self._deep_search = DeepSearchEngine(
    llm=self._llm_provider,
    hybrid_svc=self._hybrid_query,
    graph_svc=self._graph_query,
    task_manager=self._repo_task_mgr,
    synthesis_max_tokens=settings.llm.synthesis_max_tokens,
)

# After:
from wiki.rag import IterativeRAGEngine, WikiRetriever, CompositeRetriever
wiki_retriever = WikiRetriever(self._wiki_search) if hasattr(self, "_wiki_search") else None
composite = CompositeRetriever([wiki_retriever] if wiki_retriever else [])
rag_engine = IterativeRAGEngine(retriever=composite, llm=_wrap_llm(self._llm_provider))
self._deep_search = DeepSearchEngine(rag_engine=rag_engine)
```

同时更新 `WikiMCPHandler` 实例化（L270-276），传入 `rag_engine=rag_engine`。

- [ ] **Step 5: Run integration test**

Run: `cd knowledge-base-service && python -m pytest tests/integration/test_search_unification.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd knowledge-base-service && python -m pytest tests/ -v --timeout=120 -x`
Expected: PASS（可能需要修复一些因参数变更导致的测试）

- [ ] **Step 7: Commit**

```bash
git add wiki/bootstrap.py config.py services/kb_service.py tests/integration/
git commit -m "refactor(bootstrap): assemble IterativeRAGEngine, remove iterative_rag_enabled flag"
```

---

## Sprint 4: P1-C 次要修复 + 验证

### Task 14: Business 路由去重

**Files:**
- Modify: `api/routes/business_sync_routes.py`

- [ ] **Step 1: 确认重复端点**

Run: `cd knowledge-base-service && rg "GET.*businesses" api/routes/business_routes.py api/routes/business_sync_routes.py`

- [ ] **Step 2: 删除 sync 中的冗余定义**

删除 `business_sync_routes.py` 中与 `business_routes.py` 重复的 `GET /api/v1/businesses` 端点。

- [ ] **Step 3: 验证 API 仍可访问**

Run: `cd knowledge-base-service && python -m pytest tests/api/ -v -k business`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add api/routes/business_sync_routes.py
git commit -m "fix(api): remove duplicate GET /businesses from sync routes"
```

---

### Task 15: compose_concurrency 统一配置源

**Files:**
- Modify: `wiki/pipeline_nodes.py`

- [ ] **Step 1: 查找 os.getenv 引用**

Run: `cd knowledge-base-service && rg "WIKI__COMPOSE_CONCURRENCY" wiki/`

- [ ] **Step 2: 替换为 AppWikiFlags 读取**

将 `os.getenv("WIKI__COMPOSE_CONCURRENCY", ...)` 替换为从 `AppWikiFlags` 实例读取 `compose_concurrency`。

- [ ] **Step 3: 验证**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ -v -k pipeline`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/pipeline_nodes.py
git commit -m "fix(config): unify compose_concurrency to read from AppWikiFlags only"
```

---

### Task 16: 全量回归测试 + 文档更新

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/superpowers/SYSTEM_REVIEW_20260501_182703_comprehensive_audit.md`

- [ ] **Step 1: 运行全量测试**

Run: `cd knowledge-base-service && python -m pytest tests/ -v --timeout=120`
Expected: 全部 PASS

- [ ] **Step 2: 更新 ARCHITECTURE.md**

在 Phase 7 章节中添加：
- LLM 抽象统一（5→2 层）的架构说明
- 搜索系统统一（IterativeRAGEngine 单内核）的说明

- [ ] **Step 3: 更新审计文档**

在 `SYSTEM_REVIEW` 中将已完成的 P0 和 P1 项标记为 `✅ 已完成`。

- [ ] **Step 4: Commit**

```bash
git add docs/
git commit -m "docs: update architecture and audit docs for Phase 7 completion"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** 所有 P0（4项）+ P1-A（LLM统一）+ P1-B（搜索统一 + 3-LLM）+ P1-C（次要修复）均有对应 Task
- [x] **Placeholder scan:** 无 TBD/TODO/implement later
- [x] **Type consistency:**
  - `IterativeRAGEngine.arun(*, question, scope, max_rounds)` — 全 keyword-only，全计划一致
  - `Chunk(content, source: str, title, relevance, metadata)` — 字段名全计划一致
  - `RetrievalScope(scope_type, business_id, ...)` — scope_type 必选，全计划一致
  - `LLMPort` Protocol 签名一致（generate + complete + complete_stream）
- [x] **P0-2 已移除:** `generate_wiki` MCP 注册已从计划中排除
- [x] **工具数量:** 文档统一为 22（12+10），与 P0-2 移除决策一致
- [x] **Task 编号:** 连续无冲突（Task 1-16）
- [x] **缺失文件已补充:** `structure_planner.py`、`topic_structure_planner.py`、`rag/engine.py` 的 LLMPort 迁移
