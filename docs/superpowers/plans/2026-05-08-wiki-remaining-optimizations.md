# Wiki 生成剩余优化项实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix CCB call chain bug, fuse CCB+Agent-Driven generation paths, add graph-based pre-grouping for domain classification, merge small leaf domains at compose, and fix empty graph edges in hierarchy decomposition.

**Architecture:** Layered approach — fix data layer (R1 CCB), then fuse generation paths (R5 CCB+Agent), then classification layer (R2c empty edges → R2a pre-grouping → R2b prompt injection), then compose layer (R3 leaf merge). Each layer change is independently testable.

**Tech Stack:** Python 3.11, pytest, asyncio, FalkorDB Cypher, LangGraph pipeline

**Spec:** `docs/superpowers/specs/2026-05-08-wiki-remaining-optimizations-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `wiki/content_context_builder.py` | R1: Fix `_query_call_chains` to use `caller_functions`/`callee_functions` |
| Modify | `wiki/nodes/classify.py` | R2c: Load real graph edges in `decompose_hierarchy_node` |
| Create | `wiki/graph_pre_grouper.py` | R2a: Union-Find connected components + directory prefix |
| Modify | `wiki/nodes/classify.py` | R2a: Inject pre_groups into classify_domains_node |
| Modify | `wiki/cross_repo_domain_planner.py` | R2b: Add pre_groups to classification prompt |
| Modify | `wiki/nodes/compose.py` | R3: `_merge_small_leaves` before topo sort |
| Modify | `wiki/nodes/compose.py` | R5: Fuse CCB+Agent — CCB always runs first, feeds Agent |
| Modify | `wiki/content_context_builder.py` | R5: Enhance `format_summary_for_agent` |
| Modify | `wiki/page_agent.py` | R5: Increase baseline_str limit |
| Create | `tests/wiki/test_ccb_caller_functions.py` | R1 tests |
| Create | `tests/wiki/test_decompose_real_edges.py` | R2c tests |
| Create | `tests/wiki/test_graph_pre_grouper.py` | R2a tests |
| Create | `tests/wiki/test_planner_pre_groups_prompt.py` | R2b tests |
| Create | `tests/wiki/test_compose_merge_small_leaves.py` | R3 tests |

---

### Task 1: R1 — Fix CCB Call Chain Bug + Use caller_functions/callee_functions

**Files:**
- Modify: `wiki/content_context_builder.py:415-439`
- Test: `tests/wiki/test_ccb_caller_functions.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_ccb_caller_functions.py`:

```python
"""Test that _query_call_chains reads caller_functions/callee_functions from module rows."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

import pytest


@dataclass
class _FakeResult:
    data: list


@pytest.fixture
def mock_graph():
    graph = AsyncMock()
    graph.execute_query = AsyncMock()
    return graph


def test_caller_functions_used_from_module_rows(mock_graph):
    """When module_rows contain caller_functions/callee_functions, those should populate CallChainStep."""
    from wiki.content_context_builder import ContentContextBuilder, CallChainStep

    module_rows = _FakeResult(data=[
        {
            "caller": "ModuleA",
            "callee": "ModuleB",
            "caller_functions": ["handleRequest", "processData"],
            "callee_functions": ["save", "validate"],
        },
        {
            "caller": "ModuleB",
            "callee": "ModuleC",
            "caller_functions": [],
            "callee_functions": ["notify"],
        },
    ])
    method_rows = _FakeResult(data=[])

    mock_graph.execute_query = AsyncMock(side_effect=[module_rows, method_rows])

    ccb = ContentContextBuilder.__new__(ContentContextBuilder)
    ccb._graph = mock_graph

    steps = asyncio.get_event_loop().run_until_complete(
        ccb._query_call_chains(["ModuleA", "ModuleB"], depth=2)
    )

    assert len(steps) == 2
    assert steps[0].caller_method == "handleRequest"
    assert steps[0].callee_method == "save"
    assert steps[1].caller_method == ""
    assert steps[1].callee_method == "notify"


def test_old_method_map_bug_not_present(mock_graph):
    """All rows should NOT share the same caller_method — the old bug."""
    from wiki.content_context_builder import ContentContextBuilder

    module_rows = _FakeResult(data=[
        {"caller": "A", "callee": "B", "caller_functions": ["fn1"], "callee_functions": ["fn2"]},
        {"caller": "C", "callee": "D", "caller_functions": ["fn3"], "callee_functions": ["fn4"]},
    ])
    method_rows = _FakeResult(data=[])

    mock_graph.execute_query = AsyncMock(side_effect=[module_rows, method_rows])

    ccb = ContentContextBuilder.__new__(ContentContextBuilder)
    ccb._graph = mock_graph

    steps = asyncio.get_event_loop().run_until_complete(
        ccb._query_call_chains(["A", "C"], depth=2)
    )

    assert steps[0].caller_method == "fn1"
    assert steps[1].caller_method == "fn3"
    assert steps[0].caller_method != steps[1].caller_method
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_ccb_caller_functions.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: FAIL (old code ignores `caller_functions`, uses method_map bug)

- [x] **Step 3: Write minimal implementation**

In `wiki/content_context_builder.py`, replace lines 415-439 (the `if module_rows:` branch):

**Delete** the entire `method_map` construction and iteration block. **Replace with:**

```python
        if module_rows:
            for row in module_rows:
                caller = str(row.get("caller", "") or "")
                callee = str(row.get("callee", "") or "")
                caller_fns = row.get("caller_functions") or []
                callee_fns = row.get("callee_functions") or []
                steps.append(
                    CallChainStep(
                        caller=caller,
                        callee=callee,
                        caller_method=str(caller_fns[0]) if caller_fns else "",
                        callee_method=str(callee_fns[0]) if callee_fns else "",
                        relationship="CALLS",
                    ),
                )
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_ccb_caller_functions.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: PASS

- [x] **Step 5: Run full test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/content_context_builder.py tests/wiki/test_ccb_caller_functions.py
git commit -m "fix: use caller_functions/callee_functions in CCB call chain, remove buggy method_map"
```

---

### Task 1.5: R5 — Fuse CCB + Agent-Driven Generation Paths

**Files:**
- Modify: `wiki/nodes/compose.py:250-360` (refactor `_compose_single_leaf_domain`)
- Modify: `wiki/content_context_builder.py:118-163` (enhance `format_summary_for_agent`)
- Modify: `wiki/page_agent.py:627` (increase `baseline_str` limit)
- Test: `tests/wiki/test_ccb_agent_fusion.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_ccb_agent_fusion.py`:

```python
"""Test that CCB + Agent-Driven fusion: CCB always runs first, Agent uses CCB context."""
import ast
import inspect

import pytest


def test_compose_runs_ccb_before_agent():
    """In _compose_single_leaf_domain, CCB context building should appear before Agent check."""
    from wiki.nodes import compose as compose_mod
    source = inspect.getsource(compose_mod._compose_single_leaf_domain)

    ccb_pos = source.find("ContentContextBuilder")
    agent_pos = source.find("AgentConfig")

    assert ccb_pos != -1, "ContentContextBuilder should be used in _compose_single_leaf_domain"
    assert agent_pos != -1, "AgentConfig should be used in _compose_single_leaf_domain"
    assert ccb_pos < agent_pos, (
        "CCB context building should appear BEFORE AgentConfig check — "
        "CCB must always run first to provide baseline context to Agent"
    )


def test_agent_runs_even_without_ccb_context():
    """Agent-Driven path should check 'llm is not None and graph_store is not None', not 'context is not None'."""
    from wiki.nodes import compose as compose_mod
    source = inspect.getsource(compose_mod._compose_single_leaf_domain)
    # Agent check should not be gated on context being non-None
    assert "if context is not None and llm" not in source.split("AgentConfig")[0][-200:]


def test_agent_uses_format_summary_for_agent():
    """Agent path should use format_summary_for_agent for rich baseline context."""
    from wiki.nodes import compose as compose_mod
    source = inspect.getsource(compose_mod._compose_single_leaf_domain)
    assert "format_summary_for_agent" in source, (
        "Agent path should use format_summary_for_agent to pass CCB context"
    )


def test_format_summary_includes_module_summaries():
    """format_summary_for_agent should include module_leaf_summaries section."""
    from wiki.content_context_builder import EnrichedDomainContext
    ctx = EnrichedDomainContext(domain_name="TestDomain")
    ctx.module_leaf_summaries = {"ModA": "Handles auth", "ModB": "Handles payments"}
    summary = ctx.format_summary_for_agent(max_chars=6000)
    assert "ModA" in summary
    assert "Handles auth" in summary


def test_baseline_str_limit_increased():
    """page_agent.generate should use baseline_str with > 2000 char limit."""
    from wiki import page_agent
    source = inspect.getsource(page_agent.WikiPageAgent.generate)
    # Should NOT truncate to 2000
    assert "[:2000]" not in source or "[:6000]" in source or "[:8000]" in source
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_ccb_agent_fusion.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: FAIL (CCB appears after AgentConfig in current code, format_summary_for_agent not called, module_summaries not in format output)

- [x] **Step 3a: Enhance `format_summary_for_agent`**

In `wiki/content_context_builder.py`, modify `format_summary_for_agent` (around line 118-163):

After the existing `external_callers` section, add:

```python
        if self.module_leaf_summaries:
            summary_lines = [
                f"  - {name}: {text[:120]}"
                for name, text in list(self.module_leaf_summaries.items())[:15]
                if text
            ]
            if summary_lines:
                sections.append("## Module Summaries\n" + "\n".join(summary_lines))

        if self.data_models:
            dm_lines = [
                f"  - {d.get('name', '?')}: fields={d.get('fields', [])[:5]}"
                for d in self.data_models[:10]
            ]
            if dm_lines:
                sections.append("## Data Models\n" + "\n".join(dm_lines))

        if self.domain_description:
            sections.insert(0, f"## Domain Description\n{self.domain_description[:500]}")
```

Also change the default `max_chars` from 2000 to 6000:
```python
    def format_summary_for_agent(self, max_chars: int = 6000) -> str:
```

- [x] **Step 3b: Increase baseline_str limit in page_agent.py**

In `wiki/page_agent.py` line 627, change:
```python
        baseline_str = str(baseline_context)[:2000]
```
to:
```python
        baseline_str = str(baseline_context)[:6000]
```

- [x] **Step 3c: Refactor `_compose_single_leaf_domain` in compose.py**

Restructure the flow so CCB runs first, then Agent uses CCB context:

**Current order** (compose.py ~L267-360):
1. Agent-Driven check (with minimal baseline)
2. CCB + TopicPageComposer
3. Legacy fallback

**New order:**
1. CCB context building (always, when graph_store available)
2. Agent-Driven check (with CCB's `format_summary_for_agent` as baseline)
3. TopicPageComposer (using same CCB context)
4. Legacy fallback

Replace the Agent-Driven block (L267-311) and CCB block (L313-357) with:

```python
    # --- Step 1: Always run CCB to collect structured context ---
    context = None
    covered_entity_uids: list[str] = []
    if graph_store is not None:
        from wiki.content_context_builder import ContentContextBuilder
        try:
            ccb = ContentContextBuilder(graph_store, wiki_store=wiki_store)
            context = await ccb.build_context(
                domain_name=domain_name,
                module_names=list(module_names),
                module_index=module_index,
                entity_roles=entity_roles,
                domain_mapping=domain_mapping or {},
                depth=2,
                parent_domain=str(leaf.get("parent") or "root"),
            )
            if module_summaries:
                names_set = set(module_names)
                relevant = {
                    k: str(v.get("summary_text", ""))
                    for k, v in module_summaries.items()
                    if k in names_set and v.get("summary_text")
                }
                context.module_leaf_summaries = relevant
            covered_entity_uids = [e.uid for e in context.biz_entities] + [
                str(d["uid"]) for d in context.data_models if d.get("uid")
            ]
        except Exception:
            _pn.log.warning("ccb_context_build_failed", domain=domain_name, exc_info=True)

    # --- Step 2: Agent-Driven path (uses CCB context as rich baseline; runs even if CCB failed) ---
    if llm is not None and graph_store is not None:
        from wiki.agent_config import AgentConfig
        agent_cfg = AgentConfig.from_env()
        if agent_cfg.should_use_agent(len(module_names)):
            try:
                from wiki.page_agent import WikiPageAgent
                agent = WikiPageAgent(llm, graph_store)
                ccb_summary = context.format_summary_for_agent(max_chars=6000) if context else ""
                content = await agent.generate(
                    module_names=list(module_names),
                    domain_name=domain_name,
                    baseline_context=ccb_summary or None,
                    max_rounds=5,
                )
                if content and len(content) > 100:
                    page = {
                        "title": domain_name,
                        "content": content,
                        "path": f"wiki/{domain_name}",
                        "page_type": "topic",
                        "domain": domain_name,
                        "covered_entity_uids": covered_entity_uids,
                    }
                    pages = [page]
                    known_entities = [
                        {"name": e.name, "repository": e.repository, "file_path": e.file_path,
                         "start_line": max(m.start_line for m in e.methods) if e.methods else 0}
                        for e in context.biz_entities
                    ]
                    _sanitize_pages(pages, known_entities, covered_entity_uids)
                    _pn.log.info("agent_driven_generation_complete", domain=domain_name)
                    return pages, [page["path"]]
            except Exception:
                _pn.log.warning("agent_driven_failed_fallback_to_composer", domain=domain_name, exc_info=True)

    # --- Step 3: TopicPageComposer path (uses same CCB context) ---
    if context is not None and llm is not None:
        try:
            overview_composer = DomainOverviewComposer(llm=llm)
            composer = _pn.TopicPageComposer(llm, token_budget=token_budget)
            pages = await composer.compose_leaf_domain_from_context(context, overview_composer=overview_composer)
            if not pages:
                return [], []
            await _generate_diagrams_for_pages(pages, llm, domain_name, module_names, module_index)
            await _enrich_pages_with_agent(pages, llm, graph_store, domain_name)
            known_entities = [
                {"name": e.name, "repository": e.repository, "file_path": e.file_path,
                 "start_line": max(m.start_line for m in e.methods) if e.methods else 0}
                for e in context.biz_entities
            ]
            _sanitize_pages(pages, known_entities, covered_entity_uids)
            return pages, [p.get("path", "") for p in pages]
        except Exception:
            _pn.log.warning("composer_failed_fallback_to_legacy", domain=domain_name, exc_info=True)

    # --- Step 4: Legacy fallback (no graph_store) ---
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_ccb_agent_fusion.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: PASS

- [x] **Step 5: Run full test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/nodes/compose.py wiki/content_context_builder.py wiki/page_agent.py tests/wiki/test_ccb_agent_fusion.py
git commit -m "feat: fuse CCB + Agent-Driven — CCB always provides context, Agent uses rich baseline"
```

---

### Task 2: R2c — Fix Empty Graph Edges in decompose_hierarchy_node

**Files:**
- Modify: `wiki/nodes/classify.py:287-288`
- Test: `tests/wiki/test_decompose_real_edges.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_decompose_real_edges.py`:

```python
"""Test that decompose_hierarchy_node loads real graph edges when graph_store is available."""
import ast
import inspect

import pytest


def test_decompose_hierarchy_node_does_not_hardcode_empty_edges():
    """Source code should NOT contain 'edges=[]' in decompose_hierarchy_node."""
    from wiki.nodes import classify as classify_mod

    source = inspect.getsource(classify_mod.decompose_hierarchy_node)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "edges":
            if isinstance(node.value, ast.List) and len(node.value.elts) == 0:
                pytest.fail(
                    "decompose_hierarchy_node still contains hardcoded 'edges=[]'. "
                    "It should load real edges from graph_store via ModuleDependencyGraph.build()."
                )


def test_decompose_hierarchy_node_imports_module_dependency_graph():
    """Source should reference ModuleDependencyGraph for loading real edges."""
    from wiki.nodes import classify as classify_mod

    source = inspect.getsource(classify_mod.decompose_hierarchy_node)
    assert "ModuleDependencyGraph" in source, (
        "decompose_hierarchy_node should use ModuleDependencyGraph to load real graph edges"
    )
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_decompose_real_edges.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: FAIL (current code has `edges=[]` hardcoded)

- [x] **Step 3: Write minimal implementation**

In `wiki/nodes/classify.py`, replace the `decompose_hierarchy_node` section around line 287-288.

**Find:**
```python
    decomposer = pn.HierarchicalDecomposer(llm, max_depth=3, min_modules_for_nesting=3)
    module_graph = ModuleGraph(modules=all_module_infos, edges=[], entry_points=[])
```

**Replace with:**
```python
    decomposer = pn.HierarchicalDecomposer(llm, max_depth=3, min_modules_for_nesting=3)

    graph_store = (config or {}).get("configurable", {}).get("graph_store")
    if graph_store is not None:
        from wiki.dependency_graph import ModuleDependencyGraph
        dep_graph = ModuleDependencyGraph(graph_store)
        repos = {repo_id for pairs in domain_mapping.items() for repo_id, _ in pairs}
        all_edges = []
        module_name_set = {m.name for m in all_module_infos}
        for repo in repos:
            try:
                repo_graph = await dep_graph.build(repo)
                all_edges.extend(repo_graph.edges)
            except Exception:
                log.warning("decompose_load_edges_failed", repo=repo, exc_info=True)
        filtered_edges = [e for e in all_edges if e.source in module_name_set and e.target in module_name_set]
        entry_points = dep_graph._identify_entry_points(all_module_infos, filtered_edges)
        module_graph = ModuleGraph(modules=all_module_infos, edges=filtered_edges, entry_points=entry_points)
    else:
        module_graph = ModuleGraph(modules=all_module_infos, edges=[], entry_points=[])
```

Also fix the **rebalance** section (~line 309) similarly:
```python
            rebal_graph = ModuleGraph(modules=leaf_modules, edges=[], entry_points=[])
```
Replace with:
```python
            rebal_edges = [e for e in filtered_edges if e.source in leaf_module_names_set or e.target in leaf_module_names_set] if graph_store is not None else []
            rebal_graph = ModuleGraph(modules=leaf_modules, edges=rebal_edges, entry_points=[])
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_decompose_real_edges.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: PASS

- [x] **Step 5: Run full test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/nodes/classify.py tests/wiki/test_decompose_real_edges.py
git commit -m "fix: load real graph edges in decompose_hierarchy_node instead of empty list"
```

---

### Task 3: R2a — Connected Components Pre-grouping

**Files:**
- Create: `wiki/graph_pre_grouper.py`
- Modify: `wiki/nodes/classify.py` (inject pre_groups computation)
- Test: `tests/wiki/test_graph_pre_grouper.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_graph_pre_grouper.py`:

```python
"""Test graph-based pre-grouping using Union-Find connected components."""
import asyncio
from unittest.mock import AsyncMock
from dataclasses import dataclass

import pytest


@dataclass
class _FakeResult:
    data: list


@pytest.fixture
def mock_graph():
    graph = AsyncMock()
    return graph


def test_connected_components_basic(mock_graph):
    """Modules connected by CALLS should be in the same group."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[
        {"source": "ModuleA", "target": "ModuleB", "weight": 5},
        {"source": "ModuleB", "target": "ModuleC", "weight": 2},
        {"source": "ModuleD", "target": "ModuleE", "weight": 1},
    ]))

    module_paths = {
        "ModuleA": "com/example/meeting/ModuleA.java",
        "ModuleB": "com/example/meeting/ModuleB.java",
        "ModuleC": "com/example/meeting/sub/ModuleC.java",
        "ModuleD": "com/example/user/ModuleD.java",
        "ModuleE": "com/example/user/ModuleE.java",
    }

    groups = asyncio.get_event_loop().run_until_complete(
        compute_pre_groups(mock_graph, ["repo1"], module_paths)
    )

    assert len(groups) == 2
    group_sizes = sorted([len(g.module_names) for g in groups])
    assert group_sizes == [2, 3]


def test_singleton_modules_excluded(mock_graph):
    """Modules with no CALLS edges should not appear in any group."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[
        {"source": "ModuleA", "target": "ModuleB", "weight": 1},
    ]))

    module_paths = {
        "ModuleA": "a/ModuleA.java",
        "ModuleB": "a/ModuleB.java",
        "ModuleC": "b/ModuleC.java",  # isolated
    }

    groups = asyncio.get_event_loop().run_until_complete(
        compute_pre_groups(mock_graph, ["repo1"], module_paths)
    )

    assert len(groups) == 1
    assert "ModuleC" not in groups[0].module_names


def test_directory_prefix_computed(mock_graph):
    """Each group should have the longest common directory prefix."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[
        {"source": "ModA", "target": "ModB", "weight": 1},
    ]))

    module_paths = {
        "ModA": "com/example/meeting/service/ModA.java",
        "ModB": "com/example/meeting/dao/ModB.java",
    }

    groups = asyncio.get_event_loop().run_until_complete(
        compute_pre_groups(mock_graph, ["repo1"], module_paths)
    )

    assert len(groups) == 1
    assert "com/example/meeting" in groups[0].directory_prefix


def test_empty_graph_returns_no_groups(mock_graph):
    """No CALLS edges should yield empty groups."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[]))

    groups = asyncio.get_event_loop().run_until_complete(
        compute_pre_groups(mock_graph, ["repo1"], {"ModA": "a/ModA.java"})
    )

    assert groups == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_graph_pre_grouper.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: FAIL (module does not exist)

- [x] **Step 3: Write minimal implementation**

Create `wiki/graph_pre_grouper.py`:

```python
"""Graph-based pre-grouping for domain classification using connected components."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.log import get_logger

log = get_logger(__name__)


@dataclass
class PreGroup:
    group_id: int
    module_names: list[str]
    directory_prefix: str


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        self._rank.setdefault(ra, 0)
        self._rank.setdefault(rb, 0)
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for node in self._parent:
            root = self.find(node)
            groups.setdefault(root, []).append(node)
        return groups


def _longest_common_prefix(paths: list[str]) -> str:
    if not paths:
        return ""
    dirs = [os.path.dirname(p) for p in paths]
    if not dirs:
        return ""
    prefix = dirs[0]
    for d in dirs[1:]:
        while not d.startswith(prefix):
            prefix = os.path.dirname(prefix)
            if not prefix:
                return ""
    return prefix


_MODULE_CALLS_CYPHER = (
    "MATCH (m1:Module {repository: $repo})-[:CONTAINS*1..3]->(f1)"
    "-[:CALLS]->(f2)<-[:CONTAINS*1..3]-(m2:Module {repository: $repo}) "
    "WHERE m1 <> m2 "
    "RETURN m1.name AS source, m2.name AS target, count(*) AS weight "
    "ORDER BY weight DESC"
)


async def compute_pre_groups(
    graph_store,
    repositories: list[str],
    module_paths: dict[str, str],
) -> list[PreGroup]:
    """Compute connected components of module CALLS graph for domain classification hints.

    Args:
        graph_store: FalkorDB graph store
        repositories: list of repository identifiers to query
        module_paths: mapping of module_name -> file path

    Returns:
        List of PreGroups (only components with >= 2 modules)
    """
    uf = _UnionFind()

    for repo in repositories:
        try:
            result = await graph_store.execute_query(_MODULE_CALLS_CYPHER, {"repo": repo})
            for row in result.data:
                source = str(row.get("source", ""))
                target = str(row.get("target", ""))
                if source and target and source in module_paths and target in module_paths:
                    uf.union(source, target)
        except Exception:
            log.warning("pre_grouper_query_failed", repo=repo, exc_info=True)

    components = uf.components()

    groups: list[PreGroup] = []
    gid = 0
    for members in components.values():
        if len(members) < 2:
            continue
        paths = [module_paths[m] for m in members if m in module_paths]
        prefix = _longest_common_prefix(paths)
        groups.append(PreGroup(group_id=gid, module_names=sorted(members), directory_prefix=prefix))
        gid += 1

    log.info("pre_groups_computed", total_groups=len(groups), total_modules=sum(len(g.module_names) for g in groups))
    return groups
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_graph_pre_grouper.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: PASS

- [x] **Step 5: Run full test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/graph_pre_grouper.py tests/wiki/test_graph_pre_grouper.py
git commit -m "feat: add graph_pre_grouper with Union-Find connected components for domain hints"
```

---

### Task 4: R2b — Inject Pre-groups into Domain Classification Prompt

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py:661-689` (`_build_single_batch_prompt`)
- Modify: `wiki/nodes/classify.py` (pass pre_groups to planner)
- Test: `tests/wiki/test_planner_pre_groups_prompt.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_planner_pre_groups_prompt.py`:

```python
"""Test that pre_groups hints are injected into domain classification prompt."""
import pytest

from wiki.graph_pre_grouper import PreGroup


def test_single_batch_prompt_contains_pre_groups():
    """When pre_groups are provided, prompt should contain 'Pre-grouping hints'."""
    from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

    planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
    planner._metadata_cache = {
        ("repo1", "ModA"): {"path": "com/meeting/ModA.java"},
        ("repo1", "ModB"): {"path": "com/meeting/ModB.java"},
    }
    planner._infrastructure_label = "Infrastructure"
    planner._module_summary = lambda repo, name: "summary"

    groups = [
        PreGroup(group_id=0, module_names=["ModA", "ModB"], directory_prefix="com/meeting"),
    ]

    prompt = planner._build_single_batch_prompt(
        "biz1",
        [("repo1", "ModA"), ("repo1", "ModB")],
        pre_groups=groups,
    )

    assert "Pre-grouping hints" in prompt
    assert "com/meeting" in prompt
    assert "ModA" in prompt
    assert "ModB" in prompt


def test_single_batch_prompt_without_pre_groups():
    """When pre_groups is None or empty, prompt should NOT contain pre-grouping section."""
    from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

    planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
    planner._metadata_cache = {("repo1", "ModA"): {"path": "a.java"}}
    planner._infrastructure_label = "Infrastructure"
    planner._module_summary = lambda repo, name: "summary"

    prompt = planner._build_single_batch_prompt("biz1", [("repo1", "ModA")])
    assert "Pre-grouping hints" not in prompt
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_planner_pre_groups_prompt.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: FAIL (`_build_single_batch_prompt` does not accept `pre_groups` parameter)

- [x] **Step 3: Write minimal implementation**

In `wiki/cross_repo_domain_planner.py`, modify `_build_single_batch_prompt`:

**Find** the method signature:
```python
    def _build_single_batch_prompt(
        self,
        business_id: str,
        pairs_in_order: list[tuple[str, str]],
    ) -> str:
```

**Replace with:**
```python
    def _build_single_batch_prompt(
        self,
        business_id: str,
        pairs_in_order: list[tuple[str, str]],
        pre_groups: list | None = None,
    ) -> str:
```

**Find** the return statement (around line 679-689):
```python
        return (
            "Classify the following modules from multiple repositories into business domains.\n"
            ...
            '"name" from the input for the given repository_id.'
        )
```

**Replace with:**
```python
        pre_group_section = ""
        if pre_groups:
            lines = ["Pre-grouping hints (modules that call each other or share directory structure):"]
            for g in pre_groups:
                prefix = g.directory_prefix or "mixed"
                names = ", ".join(g.module_names[:10])
                lines.append(f"  Group {g.group_id + 1} ({prefix}): [{names}]")
            lines.append("Use these groups as a REFERENCE — you may split or merge them as appropriate.\n")
            pre_group_section = "\n".join(lines) + "\n"

        return (
            "Classify the following modules from multiple repositories into business domains.\n"
            "Use short, human-readable domain names (e.g. product areas).\n"
            "Place shared utilities, cross-cutting helpers, or generic support modules under "
            f'the domain key "{self._infrastructure_label}" when appropriate.\n\n'
            f"Business ID: {business_id}\n\n"
            f"Modules:\n{json.dumps(rows, indent=2, ensure_ascii=False)}\n\n"
            f"{pre_group_section}"
            "Return ONLY valid JSON: an object whose keys are domain names and whose values are "
            "arrays of [repository_id, module_name] pairs. Each module_name must match a "
            '"name" from the input for the given repository_id.'
        )
```

Then update `classify_domains_node` in `wiki/nodes/classify.py` to compute and pass `pre_groups`:

After the `biz_modules` filtering section (~line 164), add:
```python
    pre_groups = None
    graph_store = (config or {}).get("configurable", {}).get("graph_store")
    if graph_store is not None:
        from wiki.graph_pre_grouper import compute_pre_groups
        module_paths = {}
        for repo, nodes in biz_modules.items():
            for n in nodes:
                name = str(n.properties.get("name", ""))
                path = str(n.properties.get("path", "") or "")
                if name:
                    module_paths[name] = path
        try:
            pre_groups = await compute_pre_groups(graph_store, list(biz_modules.keys()), module_paths)
        except Exception:
            log.warning("pre_groups_computation_failed", exc_info=True)
```

Then pass `pre_groups` to `planner.classify()` — this requires adding `pre_groups` parameter to `classify()` and forwarding to `_build_single_batch_prompt`. If `classify()` already delegates to `_build_single_batch_prompt`, thread the parameter through.

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_planner_pre_groups_prompt.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: PASS

- [x] **Step 5: Run full test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/cross_repo_domain_planner.py wiki/nodes/classify.py tests/wiki/test_planner_pre_groups_prompt.py
git commit -m "feat: inject graph pre-groups into domain classification prompt"
```

---

### Task 5: R3 — Merge Small Leaf Domains at Compose Stage

**Files:**
- Modify: `wiki/nodes/compose.py:910` (add `_merge_small_leaves` call)
- Test: `tests/wiki/test_compose_merge_small_leaves.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_compose_merge_small_leaves.py`:

```python
"""Test small leaf domain merging at compose stage."""
import pytest


def test_small_leaves_merged_into_sibling():
    """Leaves with < 3 modules should be merged into same-parent large leaf."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "Auth", "modules": ["AuthService", "AuthDAO", "AuthController"], "parent": "root"},
        {"name": "Login", "modules": ["LoginService"], "parent": "root"},
        {"name": "Payment", "modules": ["PayService", "PayDAO", "PayGateway"], "parent": "root"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 2
    login_modules_found = False
    for leaf in result:
        if "LoginService" in leaf["modules"]:
            login_modules_found = True
            assert leaf["parent"] == "root"
    assert login_modules_found


def test_all_small_leaves_first_promoted():
    """When all leaves are small, the first one should be promoted to large."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "A", "modules": ["M1"], "parent": "root"},
        {"name": "B", "modules": ["M2", "M3"], "parent": "root"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 1
    assert set(result[0]["modules"]) == {"M1", "M2", "M3"}


def test_no_merge_when_all_large():
    """When all leaves have >= min_modules, no merging should happen."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "A", "modules": ["M1", "M2", "M3"], "parent": "root"},
        {"name": "B", "modules": ["M4", "M5", "M6"], "parent": "root"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 2


def test_prefer_same_parent_for_merge():
    """Small leaves should prefer merging into same-parent large leaf."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "BigA", "modules": ["M1", "M2", "M3"], "parent": "DomainX"},
        {"name": "SmallA", "modules": ["M4"], "parent": "DomainX"},
        {"name": "BigB", "modules": ["M5", "M6", "M7"], "parent": "DomainY"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 2
    for leaf in result:
        if leaf["name"] == "BigA":
            assert "M4" in leaf["modules"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_compose_merge_small_leaves.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: FAIL (`_merge_small_leaves` does not exist)

- [x] **Step 3: Write minimal implementation**

In `wiki/nodes/compose.py`, add the function (before `compose_leaf_pages_node`):

```python
def _merge_small_leaves(
    leaves: list[dict], min_modules: int = 3
) -> list[dict]:
    """Merge leaf domains with < min_modules into sibling or nearest leaf."""
    import wiki.pipeline_nodes as _pn

    large = [l for l in leaves if len(l.get("modules", [])) >= min_modules]
    small = [l for l in leaves if len(l.get("modules", [])) < min_modules]

    if not small:
        return large

    for sl in small:
        same_parent = [l for l in large if l.get("parent") == sl.get("parent")]
        target = same_parent[0] if same_parent else (large[0] if large else None)
        if target is None:
            large.append(sl)
            continue
        target["modules"] = list(set(target.get("modules", []) + sl.get("modules", [])))
        _pn.log.info(
            "compose_leaf_merged",
            small=sl.get("name"),
            into=target.get("name"),
            added=len(sl.get("modules", [])),
        )

    return large
```

Then in `compose_leaf_pages_node`, after line 910 (`leaf_domains = _collect_leaf_domains(domain_tree)`), add:

```python
    leaf_domains = _merge_small_leaves(leaf_domains, min_modules=3)
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_compose_merge_small_leaves.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: PASS

- [x] **Step 5: Run full test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/nodes/compose.py tests/wiki/test_compose_merge_small_leaves.py
git commit -m "feat: merge small leaf domains (<3 modules) at compose stage"
```

---

### Task 6: Final Integration Smoke Test

**Files:**
- Create: `tests/wiki/test_remaining_optimizations_smoke.py`

- [x] **Step 1: Write integration smoke test**

Create `tests/wiki/test_remaining_optimizations_smoke.py`:

```python
"""Smoke test: verify all remaining optimizations are wired correctly at source level."""
import ast
import inspect

import pytest


def test_r1_ccb_no_method_map_bug():
    """CCB _query_call_chains should not contain the old method_map iteration pattern."""
    from wiki.content_context_builder import ContentContextBuilder
    source = inspect.getsource(ContentContextBuilder._query_call_chains)
    assert "method_map.items()" not in source
    assert "caller_functions" in source


def test_r2c_decompose_uses_real_edges():
    """decompose_hierarchy_node should import ModuleDependencyGraph."""
    from wiki.nodes import classify
    source = inspect.getsource(classify.decompose_hierarchy_node)
    assert "ModuleDependencyGraph" in source


def test_r2a_graph_pre_grouper_exists():
    """graph_pre_grouper module should be importable with expected API."""
    from wiki.graph_pre_grouper import compute_pre_groups, PreGroup
    assert callable(compute_pre_groups)
    assert hasattr(PreGroup, "module_names")
    assert hasattr(PreGroup, "directory_prefix")


def test_r2b_planner_accepts_pre_groups():
    """_build_single_batch_prompt should accept pre_groups parameter."""
    from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
    import inspect
    sig = inspect.signature(CrossRepoBusinessDomainPlanner._build_single_batch_prompt)
    assert "pre_groups" in sig.parameters


def test_r3_merge_small_leaves_exists():
    """_merge_small_leaves should be importable from compose module."""
    from wiki.nodes.compose import _merge_small_leaves
    assert callable(_merge_small_leaves)


def test_r3_compose_calls_merge_small_leaves():
    """compose_leaf_pages_node should call _merge_small_leaves."""
    from wiki.nodes import compose
    source = inspect.getsource(compose.compose_leaf_pages_node)
    assert "_merge_small_leaves" in source


def test_r5_ccb_before_agent_in_compose():
    """CCB context should be built before Agent check in _compose_single_leaf_domain."""
    from wiki.nodes import compose
    source = inspect.getsource(compose._compose_single_leaf_domain)
    ccb_pos = source.find("ContentContextBuilder")
    agent_pos = source.find("AgentConfig")
    assert ccb_pos < agent_pos, "CCB should run before AgentConfig check"


def test_r5_agent_uses_format_summary():
    """Agent path should reference format_summary_for_agent."""
    from wiki.nodes import compose
    source = inspect.getsource(compose._compose_single_leaf_domain)
    assert "format_summary_for_agent" in source
```

- [x] **Step 2: Run smoke test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_remaining_optimizations_smoke.py -v --no-header --no-cov 2>&1 | tail -20`
Expected: PASS

- [x] **Step 3: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 4: Commit**

```bash
git add tests/wiki/test_remaining_optimizations_smoke.py
git commit -m "test: add integration smoke test for remaining optimizations (R1-R5)"
```
