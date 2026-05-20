# Audit Remaining Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 remaining issues from the 2026-05-20 deep code audit — 5 precise bug fixes and 4 infrastructure enhancements.

**Architecture:** Surgical modifications to existing modules. No new services or packages. Each fix is self-contained with its own test.

**Tech Stack:** Python 3.11+, pytest, asyncio, FastAPI, LangGraph, React/TypeScript, Vitest

---

## Task 1: Fix ToolRegistry dispatch TypeError swallowing

**Files:**
- Modify: `wiki/agents/base_agent.py:106-111`
- Test: `tests/wiki/agents/test_base_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/agents/test_base_agent.py — add to class TestToolRegistry

@pytest.mark.asyncio
async def test_dispatch_propagates_internal_typeerror(self):
    """A TypeError INSIDE the handler must propagate, not be swallowed."""
    from wiki.agents.base_agent import ToolDef, ToolRegistry
    from wiki.agents.context import RunContext, WikiDeps
    from unittest.mock import MagicMock

    async def buggy_handler(args, ctx):
        # This TypeError is an actual bug inside the tool, not a signature mismatch
        return len(None)  # TypeError: object of type 'NoneType' has no len()

    reg = ToolRegistry()
    reg.register(ToolDef("buggy", "d", {}, buggy_handler, tier=1))

    deps = WikiDeps(graph_store=MagicMock())
    ctx = RunContext(deps=deps)
    result, _ = await reg.dispatch("buggy", {}, ctx=ctx)
    # Should report the real TypeError, not silently succeed
    assert "error" in result
    assert "NoneType" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/agents/test_base_agent.py::TestToolRegistry::test_dispatch_propagates_internal_typeerror -xvs`
Expected: FAIL — currently the TypeError is caught and handler is re-called without ctx, which also fails but in a confusing way.

- [ ] **Step 3: Write minimal implementation**

Replace lines 106-111 in `wiki/agents/base_agent.py`:

```python
        try:
            if ctx is not None:
                import inspect
                sig = inspect.signature(tool.handler)
                accepts_ctx = "ctx" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                if accepts_ctx:
                    result = await tool.handler(validated_args, ctx)
                else:
                    result = await tool.handler(validated_args)
            else:
                result = await tool.handler(validated_args)
        except Exception as exc:
            log.warning("tool_dispatch_error", tool=name, exc_info=True)
            err = {"error": str(exc)}
            return err, json.dumps(err, ensure_ascii=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/agents/test_base_agent.py -xvs`
Expected: ALL PASS (including existing `test_dispatch_passes_ctx_to_handler` and `test_dispatch_falls_back_when_handler_rejects_ctx`)

- [ ] **Step 5: Commit**

```bash
git add wiki/agents/base_agent.py tests/wiki/agents/test_base_agent.py
git commit -m "fix: use inspect.signature to route ctx instead of catching TypeError"
```

---

## Task 2: Fix run_generation silent empty string on failure

**Files:**
- Modify: `wiki/agents/base_agent.py:256-260`
- Test: `tests/wiki/agents/test_base_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/agents/test_base_agent.py — add new class

class TestRunGenerationError:
    @pytest.mark.asyncio
    async def test_run_generation_raises_on_llm_failure(self):
        """LLM failure must raise LLMGenerationError, not return empty string."""
        from wiki.agents.base_agent import LLMGenerationError

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("model overloaded"))

        agent = ConcreteAgent(mock_llm)
        with pytest.raises(LLMGenerationError, match="model overloaded"):
            await agent.run_generation("system", "user prompt")

    @pytest.mark.asyncio
    async def test_run_generation_returns_text_on_success(self):
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="Hello world")

        agent = ConcreteAgent(mock_llm)
        result = await agent.run_generation("system", "user prompt")
        assert result == "Hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/agents/test_base_agent.py::TestRunGenerationError::test_run_generation_raises_on_llm_failure -xvs`
Expected: FAIL — currently returns `""` instead of raising.

- [ ] **Step 3: Write minimal implementation**

Add exception class and modify `run_generation` in `wiki/agents/base_agent.py`:

```python
class LLMGenerationError(Exception):
    """Raised when the LLM fails to produce output."""
    pass
```

Modify the except block at line 258-260:

```python
        try:
            text = await self._llm.generate(prompt=user_prompt, system=system_prompt)
        except Exception as exc:
            log.warning("run_generation_failed", exc_info=True)
            raise LLMGenerationError(f"LLM generation failed: {exc}") from exc
```

- [ ] **Step 4: Fix callers that rely on empty-string fallback**

Search for call sites of `run_generation` and ensure they handle `LLMGenerationError`. Wrap in try/except where a graceful degradation makes sense:
- `wiki/page_agent.py` `write()` method: catch and return degraded content
- `wiki/agents/doc_orchestrator.py`: catch and propagate to pipeline

- [ ] **Step 5: Run all tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/agents/test_base_agent.py tests/wiki/test_page_agent.py -xvs`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/agents/base_agent.py tests/wiki/agents/test_base_agent.py
git commit -m "fix: raise LLMGenerationError instead of returning empty string on failure"
```

---

## Task 3: Fix read_code cross-repo entity collision

**Files:**
- Modify: `wiki/page_agent.py:1071-1098`
- Modify: `wiki/cypher_queries.py` (add new query)
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/test_page_agent.py — add new class

class TestReadCodeRepoFilter:
    @pytest.mark.asyncio
    async def test_read_code_filters_by_repository(self):
        """read_code should only return entities from the agent's repository."""
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {
                "name": "MyClass",
                "type": "Class",
                "file": "src/my_class.py",
                "start_line": 1,
                "end_line": 50,
                "snippet": "class MyClass: ...",
                "uid": "uid-1",
                "repository": "target-repo",
            },
        ]
        mock_graph.execute_query = AsyncMock(return_value=mock_result)

        agent = WikiPageAgent(llm=None, graph_store=mock_graph, repo_path="/path/to/target-repo")
        result = await agent.read_code("MyClass")

        # Verify the query included repository filter
        call_args = mock_graph.execute_query.call_args
        query_str = call_args[0][0]
        params = call_args[0][1]
        assert "repository" in query_str or "repo" in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent.py::TestReadCodeRepoFilter -xvs`
Expected: FAIL — currently queries without repository filter.

- [ ] **Step 3: Write minimal implementation**

Add to `wiki/cypher_queries.py`:

```python
ENTITY_LOCATION_BY_REPO_CY = """
MATCH (f)
WHERE (f:Function OR f:Class) AND f.name = $name AND f.repository = $repo
RETURN f.name AS name, coalesce(f.file, '') AS file,
       coalesce(f.start_line, 0) AS start_line,
       coalesce(f.end_line, 0) AS end_line,
       coalesce(f.code_snippet, '') AS snippet,
       labels(f)[0] AS type,
       coalesce(f.uid, '') AS uid,
       coalesce(f.repository, '') AS repository
LIMIT 3
""".strip()
```

Modify `wiki/page_agent.py` `read_code` method (around line 1081-1083):

```python
        repo_filter = self._repository_filter()
        if repo_filter:
            from wiki.cypher_queries import ENTITY_LOCATION_BY_REPO_CY
            result = await self._graph.execute_query(
                ENTITY_LOCATION_BY_REPO_CY, {"name": entity_name, "repo": repo_filter}
            )
        else:
            from wiki.cypher_queries import ENTITY_LOCATION_CY
            result = await self._graph.execute_query(ENTITY_LOCATION_CY, {"name": entity_name})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py wiki/cypher_queries.py tests/wiki/test_page_agent.py
git commit -m "fix: filter read_code results by repository to prevent cross-repo collisions"
```

---

## Task 4: Fix WorkingMemory unlimited growth when all entries high relevance

**Files:**
- Modify: `wiki/page_agent.py:399-422`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/test_page_agent.py — add to class TestWorkingMemory

def test_enforce_limit_removes_oldest_when_all_high_relevance(self):
    """Memory must enforce limit even when all entries have high relevance."""
    wm = WorkingMemory()
    # Fill with large high-relevance entries that exceed MAX_TOTAL_CHARS
    big_snippet = "x" * 60_000
    for i in range(5):
        wm.code_snippets.append(f"[relevance:1.0] snippet_{i}: {big_snippet}")

    total_before = sum(len(e) for e in wm.code_snippets)
    assert total_before > wm.MAX_TOTAL_CHARS

    wm._enforce_limit()

    total_after = sum(
        len(e) for lst in [
            wm.code_snippets, wm.discovered_callers,
            wm.discovered_implementations, wm.discovered_call_chains,
            wm.resolved_gaps, wm.wiki_references, wm.search_findings,
        ] for e in lst
    )
    assert total_after <= wm.MAX_TOTAL_CHARS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent.py::TestWorkingMemory::test_enforce_limit_removes_oldest_when_all_high_relevance -xvs`
Expected: FAIL — current code only removes entries with relevance == 0 first, then removes from first available list, but may not reach the target.

- [ ] **Step 3: Write minimal implementation**

Replace the second `while` block in `_enforce_limit` (lines 413-421 in `wiki/page_agent.py`):

```python
        while total > self.MAX_TOTAL_CHARS:
            removed = False
            for lst in all_lists:
                if lst:
                    total -= len(lst[0])
                    del lst[0]
                    removed = True
                    break
            if not removed:
                break
```

This loop already exists — verify it handles the case where the FIRST loop (relevance==0 filter) doesn't remove anything. The issue is if `_relevance()` never returns 0 for these entries. Check the `_relevance` function and verify the test scenario triggers the second loop correctly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent.py::TestWorkingMemory -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "fix: ensure WorkingMemory enforces limit even with all high-relevance entries"
```

---

## Task 5: Fix trigger_page_regeneration bare task lifecycle

**Files:**
- Modify: `wiki/service.py:1742-1748`
- Test: `tests/wiki/test_service_enrichment.py` (or new test file)

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/test_service_task_lifecycle.py (new file)

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_bare_create_task_tracked_and_cancellable():
    """When no task_supervisor, bare asyncio.create_task must be tracked."""
    from wiki.service import WikiService
    from core.config import AppWikiFlags, EmbeddingConfig

    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[{
        "domain": "test", "repository": "repo", "title": "Page", "uid": "uid-1",
    }]))

    wiki_cfg = AppWikiFlags()
    emb_cfg = EmbeddingConfig()

    with patch("wiki.service.get_settings") as mock_settings:
        mock_settings.return_value.llm = MagicMock(max_context_tokens=128_000)
        svc = WikiService(
            graph=mock_graph,
            llm=None,
            repository_exists=AsyncMock(return_value=True),
            wiki_config=wiki_cfg,
            embedding_config=emb_cfg,
            task_supervisor=None,  # No supervisor — uses bare asyncio.create_task
        )

    result = await svc.trigger_page_regeneration("uid-1")
    assert result["status"] == "accepted"

    # The task should be tracked
    assert hasattr(svc, "_background_tasks")
    assert len(svc._background_tasks) >= 1

    # Cancel and verify cleanup
    for t in list(svc._background_tasks):
        t.cancel()
    await asyncio.gather(*svc._background_tasks, return_exceptions=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_service_task_lifecycle.py -xvs`
Expected: FAIL — `_background_tasks` attribute does not exist.

- [ ] **Step 3: Write minimal implementation**

In `wiki/service.py`, add to `WikiService.__init__` (after line 169):

```python
        self._background_tasks: set[asyncio.Task] = set()
```

Modify line 1748 (the `else` branch of `trigger_page_regeneration`):

```python
        else:
            task = asyncio.create_task(_run_regeneration())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_service_task_lifecycle.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/service.py tests/wiki/test_service_task_lifecycle.py
git commit -m "fix: track bare asyncio.create_task in WikiService for graceful shutdown"
```

---

## Task 6: Fix generate_stream_events single-page failure kills stream

**Files:**
- Modify: `wiki/service.py:904-961`
- Test: `tests/wiki/test_service_enrichment.py` or new test

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/test_service_stream_isolation.py (new file)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_stream_continues_after_single_page_compose_failure():
    """A compose error for one page must not abort the entire stream."""
    from wiki.service import WikiService
    from core.config import AppWikiFlags, EmbeddingConfig

    wiki_cfg = AppWikiFlags()
    emb_cfg = EmbeddingConfig()
    mock_graph = MagicMock()

    with patch("wiki.service.get_settings") as mock_settings:
        mock_settings.return_value.llm = MagicMock(max_context_tokens=128_000)
        svc = WikiService(
            graph=mock_graph,
            llm=MagicMock(),
            repository_exists=AsyncMock(return_value=True),
            wiki_config=wiki_cfg,
            embedding_config=emb_cfg,
        )

    # Mock the internal stream to yield pages, one of which raises
    pages_data = []

    async def mock_generate_stream(*args, **kwargs):
        # Simulate: first page OK, second fails, third OK
        yield {"page": {"title": "Page1", "path": "/p1"}}
        raise RuntimeError("compose failed for page2")

    with patch.object(svc, "_generate_wiki_stream", mock_generate_stream):
        events = []
        async for event in svc.generate_stream_events("repo", language="en"):
            events.append(event)

    # Stream should contain error event but not crash
    error_events = [e for e in events if e.get("type") == "error" or "error" in str(e)]
    assert len(error_events) >= 1 or any("error" in str(e) for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_service_stream_isolation.py -xvs`
Expected: FAIL — exception propagates and kills the generator.

- [ ] **Step 3: Write minimal implementation**

Wrap the inner compose loop in `generate_stream_events` with try/except:

In `wiki/service.py`, find the main loop that iterates over walk_stream results (around line 956) and wrap each page emission:

```python
        error_count = 0
        async for page in walk_stream(structure.root):
            try:
                pages.append(page)
                if config.mode == "full" and page.metadata.fallback_tier == 3:
                    degraded = True
                yield {"page": page.to_dict()}
            except Exception as exc:
                error_count += 1
                log.warning("stream_page_failed", exc_info=True)
                yield {"type": "page_error", "error": str(exc)[:200]}
                continue
```

Note: This is in the internal `_generate_wiki_pages_stream` method. Need to verify exact location and apply error isolation at the correct level.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_service_stream_isolation.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/service.py tests/wiki/test_service_stream_isolation.py
git commit -m "fix: isolate single-page compose errors in stream to prevent full abort"
```

---

## Task 7: Eliminate global TokenBudgetResolver

**Files:**
- Modify: `wiki/ask.py:152-184`
- Modify: `wiki/service.py:150`
- Test: `tests/test_wiki_ask_dynamic_budget.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/wiki/test_token_budget_isolation.py (new file)

import pytest
from wiki.token_budget import TokenBudgetResolver


def test_concurrent_resolvers_do_not_pollute():
    """Two resolvers with different budgets must not share global state."""
    from wiki.ask import _default_resolver, set_default_resolver

    resolver_a = TokenBudgetResolver(base=1000, ceiling=128_000)
    resolver_b = TokenBudgetResolver(base=5000, ceiling=128_000)

    set_default_resolver(resolver_a)
    from wiki.ask import wiki_context_token_budget

    budget_a = wiki_context_token_budget("what is X?", "concept")

    set_default_resolver(resolver_b)
    budget_b = wiki_context_token_budget("what is X?", "concept")

    # They SHOULD differ because the resolvers have different bases
    assert budget_a != budget_b, "Global state means resolvers leak across tenants"
```

- [ ] **Step 2: Run test — this test passes today (showing the bug exists)**

The test above actually demonstrates the correct symptom: changing the global leaks state. The real fix is to make the resolver explicit. Write a test that shows the API works without global:

```python
def test_wiki_context_token_budget_accepts_explicit_resolver():
    """Budget function should work with explicit resolver, no global needed."""
    from wiki.ask import wiki_context_token_budget_from_resolver

    resolver = TokenBudgetResolver(base=2000, ceiling=128_000)
    budget = wiki_context_token_budget_from_resolver("what is X?", "concept", resolver)
    assert budget > 0
```

- [ ] **Step 3: Write minimal implementation**

In `wiki/service.py` line 150, remove the call:
```python
# DELETE: set_default_resolver(self._budget_resolver)
```

In `wiki/ask.py`, modify `wiki_context_token_budget` to accept an optional `resolver` parameter:

```python
def wiki_context_token_budget(
    question: str,
    question_type: str | None,
    resolver: "TokenBudgetResolver | None" = None,
) -> int:
    effective = resolver or _default_resolver
    if effective is not None:
        return wiki_context_token_budget_from_resolver(question, question_type, effective)
    qt = question_type if question_type is not None else detect_question_type(question)
    base = _WIKI_TYPE_TOKEN_BUDGET.get(qt, 8000)
    q_tokens = max(len(question) // 4, 0)
    return min(base + q_tokens, 16000)
```

Then find all call sites of `wiki_context_token_budget` and pass the resolver explicitly where available.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -k "token_budget" -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/ask.py wiki/service.py tests/wiki/test_token_budget_isolation.py
git commit -m "fix: remove global TokenBudgetResolver mutation, pass resolver explicitly"
```

---

## Task 8: Add persistent LangGraph checkpointer

**Files:**
- Verify: `wiki/pipeline_graph.py:373-392` (already has `get_checkpointer`)
- Test: `tests/wiki/test_pipeline_graph.py`

- [ ] **Step 1: Verify existing implementation**

The codebase already has `get_checkpointer(business_id, checkpoint_dir)` at line 373. Verify it works:

```python
# In tests/wiki/test_pipeline_checkpointer.py (new file)

import os
import pytest


@pytest.mark.asyncio
async def test_get_checkpointer_creates_sqlite_saver(tmp_path):
    """get_checkpointer should return an async context manager yielding AsyncSqliteSaver."""
    from wiki.pipeline_graph import get_checkpointer

    checkpoint_dir = str(tmp_path / "checkpoints")
    async with get_checkpointer("test-biz", checkpoint_dir=checkpoint_dir) as cp:
        assert cp is not None
        # Verify DB file created
        assert os.path.exists(os.path.join(checkpoint_dir, "test-biz.db"))
```

- [ ] **Step 2: Run test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_checkpointer.py -xvs`
Expected: PASS if langgraph-checkpoint-sqlite is installed, FAIL if not.

- [ ] **Step 3: Ensure dependency is installed**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv pip install langgraph-checkpoint-sqlite`

- [ ] **Step 4: Run test again**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_checkpointer.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/wiki/test_pipeline_checkpointer.py
git commit -m "test: verify LangGraph persistent checkpointer integration"
```

---

## Task 9: Optimize GraphExplorer dagre layout (memoize)

**Files:**
- Modify: `dashboard/src/pages/GraphExplorer.tsx:132-199`
- Test: `dashboard/src/__tests__/GraphExplorer.test.tsx` (new or existing)

- [ ] **Step 1: Write the failing test**

```typescript
// In dashboard/src/__tests__/graphLayoutMemo.test.ts (new file)

import { describe, it, expect, vi } from "vitest";

describe("buildFlowNodesWithDagre memoization", () => {
  it("should not recompute layout when only highlight changes", async () => {
    // We test by importing the function and checking dagre is called once
    const dagre = await import("@dagrejs/dagre");
    const layoutSpy = vi.spyOn(dagre.default, "layout");

    const { buildFlowNodesWithDagre } = await import("../pages/GraphExplorer");

    const nodes = [{ id: "1", name: "A", type: "Function", file: "", line: 0 }];
    const edges = [];

    // First call — dagre.layout called
    buildFlowNodesWithDagre(nodes as any, edges, false, undefined);
    const callCount1 = layoutSpy.mock.calls.length;

    // Second call with same nodes/edges but different highlights
    buildFlowNodesWithDagre(nodes as any, edges, false, new Set(["1"]));
    const callCount2 = layoutSpy.mock.calls.length;

    // Currently: dagre.layout called twice (the bug)
    // After fix: should only be called once for same graph structure
    expect(callCount2).toBe(callCount1); // This FAILS before fix
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/__tests__/graphLayoutMemo.test.ts`
Expected: FAIL — dagre.layout is called on every invocation regardless of highlight changes.

- [ ] **Step 3: Write minimal implementation**

Refactor `buildFlowNodesWithDagre` to separate layout computation from styling:

```typescript
// New function: compute positions only (no styles)
function computeDagrePositions(
  apiNodes: ApiNode[],
  apiEdges: ApiEdge[],
): Map<string, { x: number; y: number }> {
  const nodeIdSet = new Set(apiNodes.map((n) => n.id));
  const g = new dagre.graphlib.Graph();
  const rankdir = hasInheritsEdges(apiEdges) ? "TB" : "LR";
  g.setGraph({ rankdir, nodesep: 60, ranksep: 80, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of apiNodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of apiEdges) {
    if (nodeIdSet.has(e.source) && nodeIdSet.has(e.target)) {
      g.setEdge(e.source, e.target);
    }
  }
  dagre.layout(g);

  const positions = new Map<string, { x: number; y: number }>();
  for (const n of apiNodes) {
    const pos = g.node(n.id);
    positions.set(n.id, { x: (pos?.x ?? 0) - NODE_WIDTH / 2, y: (pos?.y ?? 0) - NODE_HEIGHT / 2 });
  }
  return positions;
}

// In the component, use useMemo to cache positions:
const positions = useMemo(
  () => computeDagrePositions(apiNodes, apiEdges),
  [apiNodes, apiEdges],
);

// Apply styles separately (depends on theme, highlights):
const flowNodes = useMemo(
  () => applyNodeStyles(apiNodes, positions, isDark, highlightUids),
  [apiNodes, positions, isDark, highlightUids],
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run src/__tests__/graphLayoutMemo.test.ts`
Expected: PASS

- [ ] **Step 5: Run full frontend tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm vitest run`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/GraphExplorer.tsx dashboard/src/__tests__/graphLayoutMemo.test.ts
git commit -m "perf: memoize dagre layout, only recompute when graph structure changes"
```

---

## Execution Order

```
Task 1 (ToolRegistry dispatch)  ─┐
Task 2 (LLMGenerationError)     ─┤
Task 3 (read_code repo filter)  ─┼── Sprint 1 (parallel)
Task 4 (WorkingMemory limit)    ─┤
Task 5 (task lifecycle)         ─┘
                                  │
Task 6 (stream isolation)       ──┤
Task 7 (TokenBudget global)     ──┼── Sprint 2 (sequential)
Task 8 (checkpointer)          ──┤
Task 9 (dagre memoize)         ──┘  (parallel with 6-8)
```
