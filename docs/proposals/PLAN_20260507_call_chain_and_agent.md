# 方法级调用链 + Cypher 解耦 + Agent Tool-Calling 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Wiki 生成流水线中增加方法级调用链构建、解耦共享 Cypher 查询、并实现 Agent Tool-Calling 框架以自动补充 CONTEXT_GAP。

**Architecture:** 三个模块递进构建：`cypher_queries.py`（共享查询常量）→ `call_chain_builder.py`（BFS 调用链）→ `page_agent.py`（Agent 框架）。调用链构建器采用单次批量 Cypher 查询 + Python BFS 算法，Agent 使用原生 OpenAI Tool-Calling API + Working Memory 模式管理上下文。

**Tech Stack:** Python 3.12, FalkorDB (OpenCypher), LangGraph, OpenAI-compatible API (tool-calling)

**Spec:** `docs/proposals/SPEC_20260507_205258_call_chain_and_agent_design.md`

**TDD Protocol:** 每个功能点遵循 Red → Green → Commit 循环。

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `wiki/cypher_queries.py` | Create | 集中管理所有共享 Cypher 查询常量 |
| `wiki/content_context_builder.py` | Modify | 改为从 cypher_queries 导入；新增 method_call_chains 字段 |
| `wiki/pipeline_nodes.py` | Modify | 改为从 cypher_queries 导入；集成 Agent enrichment |
| `wiki/call_chain_builder.py` | Create | BFS 方法级调用链构建器 |
| `wiki/unified_prompt_templates.py` | Modify | 新增调用链参考数据段 |
| `wiki/page_agent.py` | Create | Agent Tool-Calling 框架 + Working Memory |
| `wiki/llm_port.py` | Modify | 新增 complete_with_tools 方法 |
| `llm/provider.py` | Modify | 新增 complete_with_tools 方法 |
| `llm/base_provider.py` | Modify | Protocol/Bridge 新增 complete_with_tools |
| `tests/wiki/test_cypher_queries.py` | Create | Cypher 常量迁移验证 |
| `tests/wiki/test_call_chain_builder.py` | Create | BFS 算法测试 |
| `tests/wiki/test_page_agent.py` | Create | Agent 框架测试 |

---

### Task 1: 创建 `cypher_queries.py` 并迁移常量

**Files:**
- Create: `wiki/cypher_queries.py`
- Create: `tests/wiki/test_cypher_queries.py`

- [ ] **Step 1.1 RED: 写 cypher_queries 基本导入测试**

创建 `tests/wiki/test_cypher_queries.py`:

```python
"""Verify Cypher query constants are correctly exposed from cypher_queries module."""

from wiki.cypher_queries import (
    METHODS_CY,
    METHOD_CALL_CHAIN_CY,
    ENUMS_CY,
    SNIPPETS_CY,
    CHUNK_SNIPPETS_CY,
    IMPLEMENTS_CY,
    CALLERS_CY,
    FUNCTION_CALLS_CY,
    call_chain_cypher,
)


def test_all_queries_are_non_empty_strings():
    for name, cy in [
        ("METHODS_CY", METHODS_CY),
        ("METHOD_CALL_CHAIN_CY", METHOD_CALL_CHAIN_CY),
        ("ENUMS_CY", ENUMS_CY),
        ("SNIPPETS_CY", SNIPPETS_CY),
        ("CHUNK_SNIPPETS_CY", CHUNK_SNIPPETS_CY),
        ("IMPLEMENTS_CY", IMPLEMENTS_CY),
        ("CALLERS_CY", CALLERS_CY),
        ("FUNCTION_CALLS_CY", FUNCTION_CALLS_CY),
    ]:
        assert isinstance(cy, str), f"{name} should be str"
        assert len(cy) > 20, f"{name} should be non-trivial"
        assert "$names" in cy, f"{name} should use $names param"


def test_call_chain_cypher_depth():
    cy = call_chain_cypher(3)
    assert "CALLS*1..3" in cy
    cy2 = call_chain_cypher(0)
    assert "CALLS*1..1" in cy2


def test_function_calls_cy_has_module_columns():
    assert "caller_module" in FUNCTION_CALLS_CY
    assert "callee_module" in FUNCTION_CALLS_CY
```

Run: `uv run python -m pytest tests/wiki/test_cypher_queries.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 1.2 GREEN: 创建 `wiki/cypher_queries.py`**

从 `wiki/content_context_builder.py` 第 18-92 行复制所有 Cypher 常量，去掉下划线前缀，并新增 `FUNCTION_CALLS_CY`。

Run: `uv run python -m pytest tests/wiki/test_cypher_queries.py -v`
Expected: PASS

- [ ] **Step 1.3 COMMIT**

```bash
git add wiki/cypher_queries.py tests/wiki/test_cypher_queries.py
git commit -m "feat: create wiki/cypher_queries.py with shared Cypher constants"
```

---

### Task 2: 迁移 content_context_builder 的导入

**Files:**
- Modify: `wiki/content_context_builder.py`
- Test: `tests/wiki/test_cypher_queries.py` (新增后向兼容测试)

- [ ] **Step 2.1 RED: 写后向兼容导入测试**

在 `tests/wiki/test_cypher_queries.py` 追加:

```python
def test_backward_compat_imports():
    """Ensure old import paths still work after migration."""
    from wiki.content_context_builder import _IMPLEMENTS_CY, _CALLERS_CY, _SNIPPETS_CY
    assert "IMPLEMENTS" in _IMPLEMENTS_CY
    assert "caller_name" in _CALLERS_CY
    assert "code_snippet" in _SNIPPETS_CY
```

Run: `uv run python -m pytest tests/wiki/test_cypher_queries.py::test_backward_compat_imports -v`
Expected: PASS (当前仍然从本地定义导入)

- [ ] **Step 2.2 GREEN: 迁移 content_context_builder.py 的 Cypher 常量**

在 `wiki/content_context_builder.py` 顶部添加:
```python
from wiki.cypher_queries import (
    METHODS_CY as _METHODS_CY,
    call_chain_cypher as _call_chain_cypher_fn,
    METHOD_CALL_CHAIN_CY as _METHOD_CALL_CHAIN_CY,
    ENUMS_CY as _ENUMS_CY,
    SNIPPETS_CY as _SNIPPETS_CY,
    CHUNK_SNIPPETS_CY as _CHUNK_SNIPPETS_CY,
    IMPLEMENTS_CY as _IMPLEMENTS_CY,
    CALLERS_CY as _CALLERS_CY,
)
```

删除文件中原有的 `_METHODS_CY = """...` 到 `_CALLERS_CY = """...` 定义（约第 18-92 行）和 `_call_chain_cypher` 函数（约第 30-36 行）。

保留 `_call_chain_cypher` 为转发函数:
```python
def _call_chain_cypher(depth: int) -> str:
    return _call_chain_cypher_fn(depth)
```

Run: `uv run python -m pytest tests/wiki/test_cypher_queries.py tests/wiki/test_content_context_builder.py -v`
Expected: ALL PASS

- [ ] **Step 2.3 COMMIT**

```bash
git add wiki/content_context_builder.py tests/wiki/test_cypher_queries.py
git commit -m "refactor: migrate content_context_builder Cypher constants to cypher_queries"
```

---

### Task 3: 迁移 pipeline_nodes 的导入

**Files:**
- Modify: `wiki/pipeline_nodes.py`

- [ ] **Step 3.1 GREEN: 修改 pipeline_nodes.py 的导入**

将 `wiki/pipeline_nodes.py` 第 1253-1257 行的:
```python
from wiki.content_context_builder import (
    _IMPLEMENTS_CY,
    _CALLERS_CY,
    _SNIPPETS_CY,
)
```
改为:
```python
from wiki.cypher_queries import (
    IMPLEMENTS_CY as _IMPLEMENTS_CY,
    CALLERS_CY as _CALLERS_CY,
    SNIPPETS_CY as _SNIPPETS_CY,
)
```

Run: `uv run python -m pytest tests/wiki/test_pipeline_graph.py tests/wiki/test_cypher_queries.py -v`
Expected: ALL PASS

- [ ] **Step 3.2 COMMIT**

```bash
git add wiki/pipeline_nodes.py
git commit -m "refactor: pipeline_nodes imports Cypher from cypher_queries"
```

---

### Task 4: CallChainBuilder - BFS 核心算法

**Files:**
- Create: `wiki/call_chain_builder.py`
- Create: `tests/wiki/test_call_chain_builder.py`

- [ ] **Step 4.1 RED: 写 BFS 基本链路构建测试**

创建 `tests/wiki/test_call_chain_builder.py`:

```python
"""Tests for method-level call chain builder."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.call_chain_builder import CallChainBuilder, MethodCallChain, CallChainNode


def _mock_graph_store(rows: list[dict]) -> MagicMock:
    result = MagicMock()
    result.data = rows
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=result)
    return gs


class TestCallChainBuilderBasic:
    def test_empty_modules_returns_empty(self):
        gs = _mock_graph_store([])
        builder = CallChainBuilder(gs)
        chains = asyncio.get_event_loop().run_until_complete(
            builder.build_chains([])
        )
        assert chains == []

    def test_simple_two_step_chain(self):
        rows = [
            {"caller_method": "handleRequest", "callee_method": "processOrder",
             "caller_module": "OrderController", "callee_module": "OrderService",
             "caller_file": "a.java", "callee_file": "b.java",
             "caller_sig": "void handleRequest()", "callee_sig": "void processOrder()"},
            {"caller_method": "processOrder", "callee_method": "saveOrder",
             "caller_module": "OrderService", "callee_module": "OrderDAO",
             "caller_file": "b.java", "callee_file": "c.java",
             "caller_sig": "void processOrder()", "callee_sig": "void saveOrder()"},
        ]
        gs = _mock_graph_store(rows)
        builder = CallChainBuilder(gs)
        chains = asyncio.get_event_loop().run_until_complete(
            builder.build_chains(["OrderController", "OrderService", "OrderDAO"])
        )
        assert len(chains) >= 1
        longest = max(chains, key=lambda c: c.depth)
        assert longest.depth >= 2
        names = [n.func_name for n in longest.chain]
        assert "handleRequest" in names
```

Run: `uv run python -m pytest tests/wiki/test_call_chain_builder.py::TestCallChainBuilderBasic -v`
Expected: FAIL (ImportError)

- [ ] **Step 4.2 GREEN: 实现 CallChainBuilder 核心**

创建 `wiki/call_chain_builder.py`，包含 `CallChainNode`、`MethodCallChain` dataclass 和 `CallChainBuilder` 类的 `build_chains()` + `_bfs()` 方法。

Run: `uv run python -m pytest tests/wiki/test_call_chain_builder.py::TestCallChainBuilderBasic -v`
Expected: PASS

- [ ] **Step 4.3 COMMIT**

```bash
git add wiki/call_chain_builder.py tests/wiki/test_call_chain_builder.py
git commit -m "feat: add CallChainBuilder with BFS chain construction"
```

---

### Task 5: CallChainBuilder - 边界条件

**Files:**
- Modify: `tests/wiki/test_call_chain_builder.py`

- [ ] **Step 5.1 RED: 写环路防护和深度限制测试**

在 `tests/wiki/test_call_chain_builder.py` 追加:

```python
class TestCallChainBuilderEdgeCases:
    def test_cycle_prevention(self):
        rows = [
            {"caller_method": "a", "callee_method": "b",
             "caller_module": "M1", "callee_module": "M2",
             "caller_file": "", "callee_file": "", "caller_sig": "", "callee_sig": ""},
            {"caller_method": "b", "callee_method": "a",
             "caller_module": "M2", "callee_module": "M1",
             "caller_file": "", "callee_file": "", "caller_sig": "", "callee_sig": ""},
        ]
        gs = _mock_graph_store(rows)
        builder = CallChainBuilder(gs)
        chains = asyncio.get_event_loop().run_until_complete(
            builder.build_chains(["M1", "M2"], max_depth=10)
        )
        for chain in chains:
            assert chain.depth <= 10
            keys = [f"{n.module_name}.{n.func_name}" for n in chain.chain]
            assert len(keys) == len(set(keys)), "cycle detected in chain"

    def test_depth_limit_respected(self):
        gs = _mock_graph_store([
            {"caller_method": f"f{i}", "callee_method": f"f{i+1}",
             "caller_module": "M", "callee_module": "M",
             "caller_file": "", "callee_file": "", "caller_sig": "", "callee_sig": ""}
            for i in range(20)
        ])
        builder = CallChainBuilder(gs)
        chains = asyncio.get_event_loop().run_until_complete(
            builder.build_chains(["M"], max_depth=3)
        )
        for chain in chains:
            assert chain.depth <= 3

    def test_max_chains_limit(self):
        rows = [
            {"caller_method": f"entry{i}", "callee_method": f"target{i}",
             "caller_module": "M", "callee_module": "M",
             "caller_file": "", "callee_file": "", "caller_sig": "", "callee_sig": ""}
            for i in range(50)
        ]
        gs = _mock_graph_store(rows)
        builder = CallChainBuilder(gs)
        chains = asyncio.get_event_loop().run_until_complete(
            builder.build_chains(["M"], max_chains=5)
        )
        assert len(chains) <= 5

    def test_graph_store_failure_returns_empty(self):
        gs = MagicMock()
        gs.execute_query = AsyncMock(side_effect=Exception("db error"))
        builder = CallChainBuilder(gs)
        chains = asyncio.get_event_loop().run_until_complete(
            builder.build_chains(["M"])
        )
        assert chains == []
```

Run: `uv run python -m pytest tests/wiki/test_call_chain_builder.py::TestCallChainBuilderEdgeCases -v`
Expected: PASS (如果 Step 4 实现正确) 或 FAIL (需要修复)

- [ ] **Step 5.2 GREEN: 修复任何失败的边界测试**

- [ ] **Step 5.3 COMMIT**

```bash
git add tests/wiki/test_call_chain_builder.py wiki/call_chain_builder.py
git commit -m "test: add edge case tests for CallChainBuilder (cycles, depth, limits)"
```

---

### Task 6: CallChainBuilder - format_for_prompt + 集成

**Files:**
- Modify: `wiki/call_chain_builder.py`
- Modify: `wiki/content_context_builder.py`
- Modify: `wiki/unified_prompt_templates.py`
- Modify: `tests/wiki/test_call_chain_builder.py`

- [ ] **Step 6.1 RED: 写 format_for_prompt 测试**

追加到 `tests/wiki/test_call_chain_builder.py`:

```python
class TestFormatForPrompt:
    def test_empty_chains(self):
        builder = CallChainBuilder(MagicMock())
        text = builder.format_for_prompt([])
        assert "无" in text

    def test_formats_chain_nodes(self):
        chains = [
            MethodCallChain(
                entry_method="handleRequest",
                entry_module="Controller",
                chain=[
                    CallChainNode("handleRequest", "Controller", "a.java", "void handleRequest()"),
                    CallChainNode("process", "Service", "b.java", "void process()"),
                ],
                depth=1,
            )
        ]
        builder = CallChainBuilder(MagicMock())
        text = builder.format_for_prompt(chains)
        assert "Controller.handleRequest" in text
        assert "Service.process" in text
        assert "→" in text
```

Run: `uv run python -m pytest tests/wiki/test_call_chain_builder.py::TestFormatForPrompt -v`
Expected: PASS

- [ ] **Step 6.2 GREEN: 在 EnrichedDomainContext 新增 method_call_chains 字段**

在 `wiki/content_context_builder.py` 的 `EnrichedDomainContext` 中新增:
```python
method_call_chains: list[dict] = field(default_factory=list)
```

在 `ContentContextBuilder.build_context` 中新增并行查询 `_query_method_call_chains`。

在 `wiki/unified_prompt_templates.py` 中新增 `build_method_call_chains_section()` 并在 `build_topic_detail_prompt` 中插入调用链段。

Run: `uv run python -m pytest tests/wiki/test_call_chain_builder.py tests/wiki/test_content_context_builder.py tests/wiki/test_unified_prompt_templates.py -v`
Expected: ALL PASS

- [ ] **Step 6.3 COMMIT**

```bash
git add wiki/call_chain_builder.py wiki/content_context_builder.py wiki/unified_prompt_templates.py tests/wiki/test_call_chain_builder.py
git commit -m "feat: integrate call chains into EnrichedDomainContext and prompts"
```

---

### 🔍 Code Review Checkpoint 1
暂停实施，对 Task 1-6 的全部变更进行 code review。

---

### Task 7: LLM Provider complete_with_tools

**Files:**
- Modify: `llm/provider.py`
- Modify: `llm/base_provider.py`
- Modify: `wiki/llm_port.py`

- [ ] **Step 7.1 RED: 写 complete_with_tools 接口测试**

在现有测试文件中追加测试，验证新方法存在且可调用。

- [ ] **Step 7.2 GREEN: 在 LLMProvider 中实现 complete_with_tools**

在 `llm/provider.py` 新增:
```python
async def complete_with_tools(
    self,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    model: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model or self._config.model,
        "messages": messages,
        "tools": tools,
        "temperature": self._config.temperature,
        **kwargs,
    }
    data = await self._request(body)
    return data["choices"][0]["message"]
```

在 `llm/base_provider.py` 的 Protocol 和 Adapter 中新增对应方法。
在 `wiki/llm_port.py` 的 Protocol 和 Bridge 中新增对应方法。

Run: `uv run python -m pytest tests/wiki/test_llm_port.py tests/test_llm_provider.py -v`
Expected: ALL PASS

- [ ] **Step 7.3 COMMIT**

```bash
git add llm/provider.py llm/base_provider.py wiki/llm_port.py
git commit -m "feat: add complete_with_tools for native tool-calling support"
```

---

### Task 8: WikiPageAgent - WorkingMemory

**Files:**
- Create: `wiki/page_agent.py` (WorkingMemory 部分)
- Create: `tests/wiki/test_page_agent.py`

- [ ] **Step 8.1 RED: 写 WorkingMemory 测试**

创建 `tests/wiki/test_page_agent.py`:

```python
"""Tests for WikiPageAgent WorkingMemory."""

from wiki.page_agent import WorkingMemory, ToolResult


class TestWorkingMemory:
    def test_incorporate_call_chain(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_call_chain", data={
                "chains": [{"entry": "A.foo", "chain": ["A.foo", "B.bar"], "depth": 1}]
            })
        ])
        assert len(wm.discovered_call_chains) == 1

    def test_incorporate_callers(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_callers", data={
                "callers": [{"caller_name": "X", "target_name": "Y"}]
            })
        ])
        assert len(wm.discovered_callers) == 1

    def test_max_total_chars_enforced(self):
        wm = WorkingMemory()
        for i in range(100):
            wm.incorporate([
                ToolResult(tool="read_source_snippet", data={
                    "snippet": "x" * 200, "func_name": f"func{i}"
                })
            ])
        text = wm.to_prompt_section()
        assert len(text) <= WorkingMemory.MAX_TOTAL_CHARS + 500

    def test_to_prompt_section_format(self):
        wm = WorkingMemory()
        wm.discovered_call_chains.append("A → B → C")
        wm.resolved_gaps.append("gap1 resolved")
        text = wm.to_prompt_section()
        assert "A → B → C" in text
        assert "gap1" in text

    def test_empty_working_memory(self):
        wm = WorkingMemory()
        text = wm.to_prompt_section()
        assert isinstance(text, str)
```

Run: `uv run python -m pytest tests/wiki/test_page_agent.py::TestWorkingMemory -v`
Expected: FAIL (ImportError)

- [ ] **Step 8.2 GREEN: 实现 WorkingMemory**

在 `wiki/page_agent.py` 中实现 `ToolResult` dataclass 和 `WorkingMemory` 类。

Run: `uv run python -m pytest tests/wiki/test_page_agent.py::TestWorkingMemory -v`
Expected: PASS

- [ ] **Step 8.3 COMMIT**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat: implement WorkingMemory for Agent context management"
```

---

### Task 9: WikiPageAgent - Agent 循环

**Files:**
- Modify: `wiki/page_agent.py` (WikiPageAgent 部分)
- Modify: `tests/wiki/test_page_agent.py`

- [ ] **Step 9.1 RED: 写 Agent enrich 测试**

在 `tests/wiki/test_page_agent.py` 追加:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock

from wiki.page_agent import WikiPageAgent


class TestWikiPageAgent:
    def test_no_gaps_returns_original(self):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        content = "No gaps here. ## 业务概述\nSome content."
        result = asyncio.get_event_loop().run_until_complete(
            agent.enrich(content, domain_name="test")
        )
        assert result == content

    def test_with_gaps_calls_llm(self):
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(return_value={
            "content": "Enriched content without gaps.",
            "tool_calls": None,
        })
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        content = "## 业务概述\n<!-- CONTEXT_GAP: missing order flow -->"
        result = asyncio.get_event_loop().run_until_complete(
            agent.enrich(content, domain_name="test")
        )
        llm.complete_with_tools.assert_called()

    def test_max_rounds_enforced(self):
        llm = MagicMock()
        call_count = 0
        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "content": None,
                "tool_calls": [{"function": {"name": "query_callers", "arguments": '{"name":"X"}'}, "id": f"c{call_count}"}],
            }
        llm.complete_with_tools = mock_complete
        llm.generate = AsyncMock(return_value="fallback content")
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        content = "<!-- CONTEXT_GAP: x -->"
        result = asyncio.get_event_loop().run_until_complete(
            agent.enrich(content, domain_name="test")
        )
        assert call_count <= WikiPageAgent.MAX_ROUNDS
```

Run: `uv run python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent -v`
Expected: FAIL

- [ ] **Step 9.2 GREEN: 实现 WikiPageAgent.enrich()**

在 `wiki/page_agent.py` 中实现完整的 Agent 循环：Tool 定义、prompt 构建、tool_calls 解析、Tool 执行、WorkingMemory 更新、MAX_ROUNDS fallback。

Run: `uv run python -m pytest tests/wiki/test_page_agent.py -v`
Expected: ALL PASS

- [ ] **Step 9.3 COMMIT**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat: implement WikiPageAgent tool-calling loop with Working Memory"
```

---

### 🔍 Code Review Checkpoint 2
暂停实施，对 Task 7-9 的全部变更进行 code review。

---

### Task 10: 集成到 pipeline

**Files:**
- Modify: `wiki/pipeline_nodes.py`

- [ ] **Step 10.1 GREEN: 在 _compose_single_leaf_domain 中集成 Agent**

在 `wiki/pipeline_nodes.py` 的 `_compose_single_leaf_domain` 中，页面生成后、sanitize 之前添加:

```python
import re as _re
_CONTEXT_GAP_RE = _re.compile(r"<!--\s*CONTEXT_GAP:")

if llm and graph_store:
    for page_dict in pages:
        raw = page_dict.get("content", "")
        gap_count = len(_CONTEXT_GAP_RE.findall(raw))
        if gap_count > 0:
            try:
                from wiki.page_agent import WikiPageAgent
                agent = WikiPageAgent(llm, graph_store)
                enriched = await agent.enrich(raw, domain_name=domain_name)
                page_dict["content"] = enriched
                log.info("agent_enrichment_applied", domain=domain_name, gaps=gap_count)
            except Exception:
                log.warning("agent_enrichment_failed", domain=domain_name, exc_info=True)
```

Run: `uv run python -m pytest tests/wiki/test_pipeline_graph.py tests/wiki/test_compose_pages_node.py -v`
Expected: ALL PASS

- [ ] **Step 10.2 COMMIT**

```bash
git add wiki/pipeline_nodes.py
git commit -m "feat: integrate WikiPageAgent into compose pipeline for CONTEXT_GAP enrichment"
```

---

### Task 11: 更新提案文档

**Files:**
- Modify: `docs/proposals/PROPOSAL_20260507_193240_context_augmentation_strategy.md`

- [ ] **Step 11.1: 更新提案状态和实施记录**

追加 Phase 2.5 和 Phase 3A 实施结果，更新状态为 `Phase 1-3A Implemented`。

- [ ] **Step 11.2 COMMIT**

```bash
git add docs/proposals/PROPOSAL_20260507_193240_context_augmentation_strategy.md
git commit -m "docs: update proposal with Phase 2.5 and Phase 3A implementation"
```

---

### Task 12: 全量回归测试

- [ ] **Step 12.1: 运行所有相关测试**

```bash
uv run python -m pytest tests/wiki/test_cypher_queries.py tests/wiki/test_call_chain_builder.py tests/wiki/test_page_agent.py tests/wiki/test_content_context_builder.py tests/wiki/test_unified_prompt_templates.py tests/wiki/test_pipeline_graph.py tests/wiki/test_quality_evaluator.py tests/wiki/test_topic_page_composer_v2.py -v
```

Expected: ALL PASS

### 🔍 Code Review Checkpoint 3 (Final)
全部实施完成，最终 code review。
