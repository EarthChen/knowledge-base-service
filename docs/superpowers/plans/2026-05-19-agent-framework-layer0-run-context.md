# Layer 0: RunContext — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a typed dependency injection context (`RunContext[WikiDeps]`) that separates tool dependencies from the agent instance, enabling independent tool testing and natural trace_id propagation.

**Architecture:** A new `RunContext` generic dataclass wraps a `WikiDeps` typed container. `ToolDef.handler` signature changes from `(args: dict) -> dict` to `(args: dict, ctx: RunContext) -> dict`. `ToolRegistry.dispatch` passes `ctx` to handlers. `WikiPageAgent` constructs `WikiDeps` from its init params and threads it through `run_tool_loop`.

**Tech Stack:** Python 3.13, dataclasses, typing.Generic, pytest, AsyncMock

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `wiki/agents/context.py` | RunContext, WikiDeps definitions |
| Modify | `wiki/agents/base_agent.py` | ToolDef handler signature, ToolRegistry.dispatch ctx param, run_tool_loop ctx threading |
| Modify | `wiki/agents/__init__.py` | Export RunContext, WikiDeps |
| Modify | `wiki/page_agent.py` | Construct WikiDeps, pass ctx to tools, tool handlers accept ctx |
| Modify | `wiki/agents/edit_agent.py` | Same pattern as page_agent |
| Modify | `wiki/domain_doc_agent.py` | Construct WikiDeps when creating WikiPageAgent |
| Modify | `wiki/nodes/domain_compose.py` | Pass deps to agent |
| Modify | `wiki/nodes/compose.py` | Pass deps to agent |
| Modify | `wiki/nodes/heal.py` | Pass deps to agent |
| Create | `tests/wiki/agents/test_context.py` | Unit tests for RunContext/WikiDeps |
| Modify | `tests/wiki/agents/test_base_agent.py` | Update dispatch calls with ctx |
| Modify | `tests/wiki/agents/test_edit_agent.py` | Update dispatch calls with ctx |
| Modify | `tests/wiki/test_page_agent.py` | Update agent construction |

---

### Task 1: Create RunContext and WikiDeps

**Files:**
- Create: `wiki/agents/context.py`
- Create: `tests/wiki/agents/test_context.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/agents/test_context.py
from __future__ import annotations
import pytest
from unittest.mock import MagicMock


def test_wiki_deps_has_required_fields():
    from wiki.agents.context import WikiDeps

    graph = MagicMock()
    deps = WikiDeps(graph_store=graph)
    assert deps.graph_store is graph
    assert deps.search_service is None
    assert deps.repo_path is None
    assert deps.business_id == ""
    assert deps.delegation_depth == 0
    assert deps.delegation_count == 0


def test_run_context_wraps_deps():
    from wiki.agents.context import RunContext, WikiDeps

    graph = MagicMock()
    deps = WikiDeps(graph_store=graph, business_id="test-biz")
    ctx = RunContext(deps=deps, trace_id="abc123")

    assert ctx.deps.graph_store is graph
    assert ctx.deps.business_id == "test-biz"
    assert ctx.trace_id == "abc123"
    assert ctx.metadata == {}


def test_run_context_metadata_is_mutable():
    from wiki.agents.context import RunContext, WikiDeps

    ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))
    ctx.metadata["key"] = "value"
    assert ctx.metadata["key"] == "value"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/agents/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.agents.context'`

- [ ] **Step 3: Write the implementation**

```python
# wiki/agents/context.py
"""Typed dependency injection context for agent tool loops.

RunContext carries dependencies (graph store, search service, etc.)
that tools need at runtime. It is NOT sent to the LLM — only to
tool handlers, guardrails, and hooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class RunContext(Generic[T]):
    """Typed DI context threaded through tool dispatch."""
    deps: T
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WikiDeps:
    """Wiki-agent-specific dependencies."""
    graph_store: Any
    search_service: Any | None = None
    repo_path: str | None = None
    business_id: str = ""
    existing_pages: list[dict] | None = None
    delegation_depth: int = 0
    delegation_count: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/agents/test_context.py -v`
Expected: 3 passed

- [ ] **Step 5: Export from __init__.py**

Add to `wiki/agents/__init__.py`:
```python
from wiki.agents.context import RunContext, WikiDeps
```
And add `"RunContext", "WikiDeps"` to `__all__`.

- [ ] **Step 6: Commit**

```bash
git add wiki/agents/context.py tests/wiki/agents/test_context.py wiki/agents/__init__.py
git commit -m "feat(agents): add RunContext and WikiDeps for typed DI"
```

---

### Task 2: Update ToolDef and ToolRegistry to accept ctx

**Files:**
- Modify: `wiki/agents/base_agent.py`
- Modify: `tests/wiki/agents/test_base_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/wiki/agents/test_base_agent.py
@pytest.mark.asyncio
async def test_dispatch_passes_ctx_to_handler(self):
    from wiki.agents.base_agent import ToolDef, ToolRegistry
    from wiki.agents.context import RunContext, WikiDeps
    from unittest.mock import MagicMock

    received_ctx = {}

    async def handler(args, ctx):
        received_ctx["ctx"] = ctx
        return {"ok": True}

    reg = ToolRegistry()
    reg.register(ToolDef("test_tool", "d", {}, handler, tier=1))

    deps = WikiDeps(graph_store=MagicMock())
    ctx = RunContext(deps=deps, trace_id="t1")
    result, _ = await reg.dispatch("test_tool", {"x": 1}, ctx=ctx)

    assert result == {"ok": True}
    assert received_ctx["ctx"] is ctx
    assert received_ctx["ctx"].trace_id == "t1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/agents/test_base_agent.py::TestToolRegistry::test_dispatch_passes_ctx_to_handler -v`
Expected: FAIL (dispatch doesn't accept/pass ctx yet)

- [ ] **Step 3: Update ToolDef handler type and ToolRegistry.dispatch**

In `wiki/agents/base_agent.py`:

Change `ToolDef.handler` type annotation:
```python
handler: Callable[..., Awaitable[dict[str, Any]]]  # accepts (args, ctx) or (args)
```

Update `ToolRegistry.dispatch` to pass `ctx`:
```python
async def dispatch(
    self, name: str, args: dict[str, Any], *, post_call: bool = False, ctx: Any = None
) -> tuple[dict[str, Any], str]:
    # ... existing validation ...
    try:
        if ctx is not None:
            result = await tool.handler(validated_args, ctx)
        else:
            result = await tool.handler(validated_args)
    except Exception as exc:
        # ... existing error handling ...
```

Update `run_tool_loop` to build and pass ctx:
```python
async def run_tool_loop(self, system_prompt, user_prompt, memory, *, config=None, ctx=None, ...):
    # ... in the tool dispatch section:
    result, result_str = await self._tool_registry.dispatch(
        tool_name, args, post_call=config.enable_post_call_guardrail, ctx=ctx
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/agents/test_base_agent.py -v`
Expected: All tests pass

- [ ] **Step 5: Run full agent test suite**

Run: `uv run pytest tests/wiki/agents/ --no-cov -q`
Expected: All tests pass (existing tests pass ctx=None by default)

- [ ] **Step 6: Commit**

```bash
git add wiki/agents/base_agent.py tests/wiki/agents/test_base_agent.py
git commit -m "feat(agents): ToolRegistry.dispatch accepts RunContext"
```

---

### Task 3: Migrate WikiPageAgent tool handlers to accept ctx

**Files:**
- Modify: `wiki/page_agent.py`
- Modify: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write a test that verifies ctx is passed to tool handlers**

```python
# Add to tests/wiki/test_page_agent.py
@pytest.mark.asyncio
async def test_explore_passes_ctx_with_graph_store():
    from wiki.agents.context import WikiDeps
    mock_llm = MagicMock()
    mock_graph = MagicMock()

    mock_llm.complete_with_tools = AsyncMock(side_effect=[
        {"tool_calls": [{"id": "tc1", "function": {"name": "query_module_detail", "arguments": '{"name": "Mod"}'}}], "content": None},
        {"tool_calls": None, "content": "done"},
    ])

    deps = WikiDeps(graph_store=mock_graph)
    agent = WikiPageAgent(mock_llm, deps=deps, max_rounds=10, max_tool_calls=100)

    # Mock the registry dispatch to capture ctx
    captured = {}
    original_dispatch = agent._tool_registry.dispatch
    async def mock_dispatch(name, args, *, post_call=False, ctx=None):
        captured["ctx"] = ctx
        return ({"name": "Mod"}, '{"name": "Mod"}')
    agent._tool_registry.dispatch = mock_dispatch

    await agent.explore(module_names=["Mod"], domain_name="d", baseline_context="b")
    assert captured.get("ctx") is not None
    assert captured["ctx"].deps.graph_store is mock_graph
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_page_agent.py::test_explore_passes_ctx_with_graph_store -v`
Expected: FAIL (WikiPageAgent doesn't accept deps= yet)

- [ ] **Step 3: Update WikiPageAgent to accept deps and build ctx**

Modify `WikiPageAgent.__init__`:
```python
def __init__(
    self,
    llm: Any,
    graph_store: Any = None,
    *,
    deps: WikiDeps | None = None,
    repo_path: str | None = None,
    search_service: Any | None = None,
    max_rounds: int = 6,
    max_tool_calls: int = 30,
) -> None:
    super().__init__(llm, max_rounds=max_rounds, max_tool_calls=max_tool_calls)
    # Support both old (graph_store positional) and new (deps=) interface
    if deps is not None:
        self._deps = deps
    else:
        self._deps = WikiDeps(
            graph_store=graph_store,
            search_service=search_service,
            repo_path=repo_path,
        )
    self._graph = self._deps.graph_store
    self._repo_path = self._deps.repo_path
    self._search_service = self._deps.search_service
    # ... rest unchanged ...
```

Modify `explore()` to pass ctx:
```python
async def explore(self, ...):
    from wiki.agents.context import RunContext
    ctx = RunContext(deps=self._deps)
    memory = await self.run_tool_loop(system, user_prompt, memory, config=config, ctx=ctx)
    # ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_page_agent.py --no-cov -q`
Expected: All pass

- [ ] **Step 5: Update tool handlers to accept ctx (gradual)**

Update each `_tool_*` method signature to accept `ctx` as second param (after args). For now, they can ignore it since `self._graph` still exists as a fallback:

```python
async def _tool_query_module_detail(self, args: dict[str, Any]) -> dict[str, Any]:
    # No change needed yet — still uses self._graph
    # ctx will be used in a follow-up when we remove self._graph
```

This step is optional for Layer 0 — the key achievement is that ctx is passed through the dispatch chain.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/wiki/ --no-cov -q`
Expected: All 2469+ tests pass

- [ ] **Step 7: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agents): WikiPageAgent accepts WikiDeps, threads RunContext through explore"
```

---

### Task 4: Backward-compatible integration — verify all callers still work

**Why:** `WikiPageAgent.__init__` now internally constructs `WikiDeps` from its positional args. All existing callers (`domain_doc_agent.py`, `service.py`, `topic_doc_agent.py`, `heal.py`, delegation in `page_agent.py`) pass `WikiPageAgent(llm, graph_store, ...)` which maps to the old interface. Layer 0 only requires the *internal* `WikiDeps` construction — callers migrate to `deps=` in a later layer.

**Files:**
- No modifications needed for callers (backward compatible)
- Modify: `tests/wiki/agents/test_edit_agent.py` (verify dispatch with ctx)

- [ ] **Step 1: Write integration test that verifies existing caller pattern still works**

```python
# Add to tests/wiki/test_page_agent.py
@pytest.mark.asyncio
async def test_legacy_constructor_still_works():
    """Verify existing callers (graph_store positional) still function."""
    from wiki.page_agent import WikiPageAgent
    from unittest.mock import MagicMock

    llm = MagicMock()
    gs = MagicMock()
    agent = WikiPageAgent(llm, gs, repo_path="/tmp/repo", search_service=None)

    # Internal deps should be auto-constructed
    assert agent._deps.graph_store is gs
    assert agent._deps.repo_path == "/tmp/repo"
    assert agent._graph is gs
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_page_agent.py::test_legacy_constructor_still_works -v`
Expected: PASS (should already work after Task 3)

- [ ] **Step 3: Run broad integration test**

Run: `uv run pytest tests/ --no-cov -q --ignore=tests/api/test_wiki_domain_routes.py -x`
Expected: All pass — no callers broken

- [ ] **Step 4: Commit**

```bash
git add tests/wiki/test_page_agent.py
git commit -m "test(agents): verify backward-compatible constructor with implicit WikiDeps"
```

---

### Task 5: Final verification and cleanup

**Files:**
- Modify: `wiki/agents/base_agent.py` (add RunConfig.ctx field)

- [ ] **Step 1: Add ctx to RunConfig**

```python
@dataclass
class RunConfig:
    # ... existing fields ...
    ctx: Any = None  # RunContext instance, passed to tool dispatch
```

- [ ] **Step 2: Update run_tool_loop to use config.ctx when ctx param not provided**

```python
async def run_tool_loop(self, ..., *, config=None, ctx=None, ...):
    # ... existing setup ...
    effective_ctx = ctx if ctx is not None else (config.ctx if config else None)
    # ... use effective_ctx in dispatch ...
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/wiki/ --no-cov -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add wiki/agents/base_agent.py
git commit -m "feat(agents): RunConfig accepts ctx for convenience"
```

- [ ] **Step 5: Final verification**

Run: `uv run pytest tests/ --no-cov -q --ignore=tests/api/test_wiki_domain_routes.py`
Expected: All pass, zero regressions
