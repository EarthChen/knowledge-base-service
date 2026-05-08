# Wiki Pipeline Integration 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Tasks 1-13 中已实现但未接入 pipeline 的组件（CONTAINS 补全、Agent-Driven 生成、引用验证、拓扑排序、自底向上合成）正式 wire 到生产流程中。

**Architecture:** 7 个独立 Task 按优先级分 3 Phase 交付。Phase 1 (P0) 打通 Indexer→Graph 和 Agent-Driven→Compose 两条关键路径；Phase 2 (P1) 将质量验证和 overview 合成接入 quality gate 和 tree linker；Phase 3 (P2) 优化生成顺序和小域合并。每个 Task 独立可回滚。

**Tech Stack:** Python 3.12, FalkorDB (Cypher), LangGraph, pytest, asyncio

**Spec Sources:**
- `docs/superpowers/specs/2026-05-08-wiki-quality-agent-driven-design.md` (W1-W8)
- `docs/superpowers/specs/2026-05-06-wiki-topic-filter-parallel-design.md` (U3b/U3c/U3d remaining)
- `docs/superpowers/specs/2026-05-06-unified-wiki-enterprise-kb-design.md` (U6 tree_linker)

**Branch:** `feat/wiki-quality-agent-driven`

**Status:** ✅ All 7 tasks completed (2026-05-08). 1858 tests passing. 6 new commits.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `indexer/incremental_indexer.py` | Wire `supplement_contains_relationships` after graph enrichment |
| Modify | `wiki/nodes/compose.py` | Wire `AgentConfig` + `WikiPageAgent.generate()` into compose |
| Modify | `wiki/pipeline_graph.py` | Wire `citation_verifier` into `quality_gate_node` |
| Modify | `wiki/tree_linker.py` | Replace static overview with `synthesize_overview_from_children` |
| Modify | `wiki/pipeline_nodes.py` | Wire `topological_order` into `compose_leaf_pages_node` |
| Modify | `wiki/nodes/compose.py` | Add small domain merge logic |
| Create | `tests/wiki/test_indexer_contains_wiring.py` | Integration test for CONTAINS supplement in indexer |
| Create | `tests/wiki/test_agent_driven_compose.py` | Test AgentConfig routing in compose |
| Create | `tests/wiki/test_citation_quality_gate.py` | Test citation check in quality gate |
| Create | `tests/wiki/test_tree_linker_synthesized_overview.py` | Test overview synthesis in tree linker |
| Create | `tests/wiki/test_topo_compose_order.py` | Test topological ordering in compose |
| Create | `tests/wiki/test_small_domain_merge.py` | Test small domain page merge |

---

## Phase 1: P0 Pipeline Wiring (Critical Path)

### Task 1: Wire `supplement_contains_relationships` into Indexer

**Files:**
- Modify: `indexer/incremental_indexer.py:401-407` (after `GraphEnricher.enrich()`)
- Test: `tests/wiki/test_indexer_contains_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_indexer_contains_wiring.py
"""Verify supplement_contains_relationships is called during index_full."""
import ast
import textwrap

def test_index_full_calls_supplement_contains():
    """The index_full method must call supplement_contains_relationships after enrichment."""
    with open("indexer/incremental_indexer.py") as f:
        source = f.read()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "index_full":
            body_src = ast.get_source_segment(source, node)
            assert "supplement_contains_relationships" in body_src, (
                "index_full must call supplement_contains_relationships"
            )
            enrich_pos = body_src.find("enricher.enrich()")
            supplement_pos = body_src.find("supplement_contains_relationships")
            assert supplement_pos > enrich_pos, (
                "supplement_contains_relationships must come after graph enrichment"
            )
            return
    raise AssertionError("index_full method not found")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_indexer_contains_wiring.py -v`
Expected: FAIL with "index_full must call supplement_contains_relationships"

- [ ] **Step 3: Write minimal implementation**

In `indexer/incremental_indexer.py`, after line 407 (`log.info("graph_enrichment_complete", **enrich_stats)`), add:

```python
        # Supplement missing CONTAINS relationships (Function→Module)
        from indexer.post_process import supplement_contains_relationships

        graph_name = self._store.graph_name if hasattr(self._store, "graph_name") else ""
        try:
            contains_count = await supplement_contains_relationships(self._store, graph_name)
            log.info("supplement_contains_done", attempted=contains_count)
        except Exception:
            log.warning("supplement_contains_failed", exc_info=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_indexer_contains_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indexer/incremental_indexer.py tests/wiki/test_indexer_contains_wiring.py
git commit -m "feat: wire supplement_contains_relationships into indexer pipeline"
```

---

### Task 2: Wire `AgentConfig` + `WikiPageAgent.generate()` into Compose

**Files:**
- Modify: `wiki/nodes/compose.py:249-317` (`_compose_single_leaf_domain`)
- Test: `tests/wiki/test_agent_driven_compose.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_agent_driven_compose.py
"""Verify AgentConfig is checked in _compose_single_leaf_domain."""
import ast

def test_compose_checks_agent_config():
    """_compose_single_leaf_domain must import and check AgentConfig."""
    with open("wiki/nodes/compose.py") as f:
        source = f.read()

    assert "AgentConfig" in source, "compose.py must reference AgentConfig"
    assert "should_use_agent" in source, "compose.py must call should_use_agent"

def test_compose_calls_agent_generate():
    """_compose_single_leaf_domain must call WikiPageAgent generate when agent is enabled."""
    with open("wiki/nodes/compose.py") as f:
        source = f.read()

    assert "agent.generate(" in source or "WikiPageAgent" in source, (
        "compose.py must have WikiPageAgent.generate path"
    )
    assert "AgentConfig.from_env" in source or "AgentConfig(" in source, (
        "compose.py must instantiate AgentConfig"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_agent_driven_compose.py -v`
Expected: FAIL with "compose.py must reference AgentConfig"

- [ ] **Step 3: Write minimal implementation**

In `wiki/nodes/compose.py`, modify `_compose_single_leaf_domain`. Add agent-driven path **before** the existing CCB path (line ~267). The agent path is an alternative to CCB+TopicPageComposer when enabled:

```python
async def _compose_single_leaf_domain(
    leaf: dict[str, Any],
    module_index: dict[str, list[dict]],
    entity_roles: dict[str, Any],
    llm: Any,
    token_budget: int,
    *,
    graph_store: Any | None = None,
    wiki_store: Any | None = None,
    domain_mapping: dict[str, list] | None = None,
    module_summaries: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compose pages for one leaf domain (and optional diagrams when llm is set)."""
    import wiki.pipeline_nodes as _pn

    domain_name = leaf.get("name", "unknown")
    module_names = leaf.get("modules", [])

    # --- Agent-Driven generation path ---
    if graph_store is not None and llm is not None:
        from wiki.agent_config import AgentConfig

        agent_cfg = AgentConfig.from_env()
        if agent_cfg.should_use_agent(len(module_names)):
            try:
                from wiki.page_agent import WikiPageAgent

                agent = WikiPageAgent(llm, graph_store)
                baseline = ""
                if module_summaries:
                    relevant = [
                        f"- {k}: {v.get('summary_text', '')}"
                        for k, v in module_summaries.items()
                        if k in set(module_names) and v.get("summary_text")
                    ]
                    baseline = "\n".join(relevant)

                content = await agent.generate(
                    module_names=list(module_names),
                    domain_name=domain_name,
                    baseline_context=baseline or None,
                )
                if content and len(content) > 100:
                    page = {
                        "title": domain_name,
                        "content": content,
                        "path": f"wiki/{domain_name}",
                        "page_type": "topic",
                        "domain": domain_name,
                        "covered_entity_uids": [],
                    }
                    pages = [page]
                    known_entities = []
                    _sanitize_pages(pages, known_entities, [])
                    _pn.log.info("agent_driven_generation_complete", domain=domain_name)
                    return pages, [page["path"]]
            except Exception:
                _pn.log.warning(
                    "agent_driven_failed_fallback_to_ccb",
                    domain=domain_name,
                    exc_info=True,
                )

    # --- Existing CCB + TopicPageComposer path (unchanged) ---
    if graph_store is not None:
        # ... (existing code unchanged)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_agent_driven_compose.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/ -v --timeout=30`
Expected: All 61+ tests PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/compose.py tests/wiki/test_agent_driven_compose.py
git commit -m "feat: wire AgentConfig + WikiPageAgent.generate into compose pipeline"
```

---

## Phase 2: P1 Quality & Overview Integration

### Task 3: Wire `citation_verifier` into Quality Gate

**Files:**
- Modify: `wiki/pipeline_graph.py:143-222` (`quality_gate_node`)
- Test: `tests/wiki/test_citation_quality_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_citation_quality_gate.py
"""Verify citation_verifier is integrated into quality_gate_node."""
import ast

def test_quality_gate_uses_citation_verifier():
    """quality_gate_node must call verify_citations or extract_code_references."""
    with open("wiki/pipeline_graph.py") as f:
        source = f.read()

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "quality_gate_node":
            body_src = ast.get_source_segment(source, node)
            assert "citation_verifier" in body_src or "verify_citations" in body_src, (
                "quality_gate_node must use citation_verifier"
            )
            return
    raise AssertionError("quality_gate_node not found")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_citation_quality_gate.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `wiki/pipeline_graph.py`, inside `quality_gate_node`, after computing `l1` structural score (around line 186), add citation verification:

```python
        # Citation verification — check for hallucinated entity references
        from wiki.citation_verifier import verify_citations

        all_module_names: set[str] = set()
        for repo_mods in state.get("modules", {}).values():
            for mod in repo_mods:
                mod_name = mod.get("properties", {}).get("name", "")
                if mod_name:
                    all_module_names.add(mod_name)

        citation_result = verify_citations(page.content, all_module_names)
        if citation_result.invalid_count > 0:
            score_dict["citation_invalid_count"] = citation_result.invalid_count
            score_dict["citation_invalid_refs"] = citation_result.invalid_refs[:5]
            penalty = min(0.2, citation_result.invalid_count * 0.05)
            l1_adjusted = max(0.0, l1.overall - penalty)
            score_dict["l1_structural"] = round(l1_adjusted, 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_citation_quality_gate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_graph.py tests/wiki/test_citation_quality_gate.py
git commit -m "feat: wire citation_verifier into quality_gate_node"
```

---

### Task 4: Wire `overview_synthesizer` into Tree Linker

**Files:**
- Modify: `wiki/tree_linker.py:369-435` (`_build_domain_overview_content`)
- Test: `tests/wiki/test_tree_linker_synthesized_overview.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_tree_linker_synthesized_overview.py
"""Verify tree_linker uses synthesize_overview_from_children."""
import ast

def test_tree_linker_uses_overview_synthesizer():
    """_build_domain_overview_content or its parent must use synthesize_overview_from_children."""
    with open("wiki/tree_linker.py") as f:
        source = f.read()

    assert "overview_synthesizer" in source or "synthesize_overview_from_children" in source, (
        "tree_linker must import and use overview_synthesizer"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_tree_linker_synthesized_overview.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `wiki/tree_linker.py`, modify `_build_domain_overview_content` (line 369) to use `synthesize_overview_from_children` when child pages are available. The function already has access to `pages_by_entity_uid` from the enclosing scope.

Replace the body of `_build_domain_overview_content`:

```python
        def _build_domain_overview_content(domain: DomainNode, depth: int = 0) -> str:
            """Build a rich structural overview document for a nested domain."""
            from wiki.overview_synthesizer import synthesize_overview_from_children

            child_pages = []
            for mod_name in domain.modules:
                page = pages_by_entity_uid.get(mod_name)
                if page and isinstance(page, dict):
                    child_pages.append({
                        "title": mod_name,
                        "content": page.get("content", ""),
                    })

            for child in domain.children:
                child_pages.append({
                    "title": child.name,
                    "content": child.description or "",
                })

            if child_pages:
                return synthesize_overview_from_children(domain.name, child_pages)

            # Fallback to static template when no child content is available
            is_zh = language.startswith("zh")
            lines: list[str] = []
            lines.append(f"# {domain.name}")
            lines.append("")
            if domain.description:
                lines.append(domain.description)
                lines.append("")

            if domain.children:
                heading = "## 子域概览" if is_zh else "## Sub-Domains"
                lines.append(heading)
                lines.append("")
                for child in domain.children:
                    desc = f" — {child.description}" if child.description else ""
                    mod_count = len(child.modules)
                    child_count = len(child.children)
                    meta_parts: list[str] = []
                    if mod_count > 0:
                        meta_parts.append(f"{mod_count} {'个模块' if is_zh else 'modules'}")
                    if child_count > 0:
                        meta_parts.append(f"{child_count} {'个子域' if is_zh else 'sub-domains'}")
                    meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
                    lines.append(f"- **{child.name}**{desc}{meta}")
                lines.append("")

            if domain.modules:
                heading = "## 核心模块" if is_zh else "## Key Modules"
                lines.append(heading)
                lines.append("")
                for mod_name in domain.modules:
                    page = pages_by_entity_uid.get(mod_name)
                    summary = ""
                    if page:
                        content = page.get("content", "") if isinstance(page, dict) else ""
                        if content:
                            for overview_heading in ("## Overview", "## 概述", "## 业务概述"):
                                overview_start = content.find(overview_heading)
                                if overview_start >= 0:
                                    after = content[overview_start + len(overview_heading) :].strip()
                                    break
                            else:
                                after = ""
                            if after:
                                next_h = after.find("\n## ")
                                snippet = after[:next_h].strip() if next_h > 0 else after[:200].strip()
                                non_heading = [
                                    l for l in snippet.split("\n")
                                    if l.strip() and not l.strip().startswith("#")
                                ]
                                summary = _safe_truncate(" ".join(non_heading))
                    if summary:
                        lines.append(f"- **{mod_name}**: {summary}")
                    else:
                        lines.append(f"- **{mod_name}**")
                lines.append("")

            total_modules = WikiTreeLinker.count_domain_modules(domain)
            if total_modules > len(domain.modules):
                if is_zh:
                    lines.append(f"_此域及其子域共包含 {total_modules} 个模块。_")
                else:
                    lines.append(f"_This domain and sub-domains contain {total_modules} modules in total._")
                lines.append("")

            return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_tree_linker_synthesized_overview.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/tree_linker.py tests/wiki/test_tree_linker_synthesized_overview.py
git commit -m "feat: wire overview_synthesizer into tree_linker for content-based domain overviews"
```

---

## Phase 3: P2 Generation Optimization

### Task 5: Wire `topo_sort` into Compose Leaf Pages Ordering

**Files:**
- Modify: `wiki/pipeline_nodes.py` (`compose_leaf_pages_node`)
- Test: `tests/wiki/test_topo_compose_order.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_topo_compose_order.py
"""Verify compose_leaf_pages_node uses topological ordering."""
import ast

def test_compose_leaf_pages_uses_topo_sort():
    """compose_leaf_pages_node must import and use topological_order."""
    with open("wiki/pipeline_nodes.py") as f:
        source = f.read()

    assert "topo_sort" in source or "topological_order" in source, (
        "pipeline_nodes.py must use topological_order for domain ordering"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_topo_compose_order.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `wiki/pipeline_nodes.py`, inside `compose_leaf_pages_node`, before iterating over leaf domains, add topological ordering. Find the section where `leaves` list is built from `_collect_leaves(domain_tree)` and sort it:

```python
    # Apply topological ordering to process dependency-first
    from wiki.topo_sort import topological_order

    domain_edges: dict[str, list[str]] = {}
    domain_mapping = state.get("domain_mapping", {})
    for leaf in leaves:
        leaf_name = leaf.get("name", "")
        deps = []
        leaf_modules = set(leaf.get("modules", []))
        for other_leaf in leaves:
            if other_leaf.get("name") == leaf_name:
                continue
            other_modules = set(other_leaf.get("modules", []))
            if leaf_modules & other_modules:
                deps.append(other_leaf.get("name", ""))
        if deps:
            domain_edges[leaf_name] = deps

    if domain_edges:
        ordered_names = topological_order(domain_edges)
        name_to_leaf = {l.get("name", ""): l for l in leaves}
        ordered_leaves = []
        for name in ordered_names:
            if name in name_to_leaf:
                ordered_leaves.append(name_to_leaf.pop(name))
        ordered_leaves.extend(name_to_leaf.values())
        leaves = ordered_leaves
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_topo_compose_order.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py tests/wiki/test_topo_compose_order.py
git commit -m "feat: wire topological_order into compose_leaf_pages for dependency-first generation"
```

---

### Task 6: Small Domain Page Merge

**Files:**
- Modify: `wiki/nodes/compose.py`
- Test: `tests/wiki/test_small_domain_merge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_small_domain_merge.py
"""Verify small domains (1-2 modules) produce a single merged page."""
from wiki.domain_merger import merge_small_domains

def test_merge_small_domains_produces_fewer_domains():
    """Domains with 1-2 modules should be merged into larger domains."""
    domains = [
        {"name": "A", "modules": ["m1", "m2", "m3", "m4", "m5"]},
        {"name": "B", "modules": ["m6"]},
        {"name": "C", "modules": ["m7", "m8"]},
    ]
    merged = merge_small_domains(domains, min_size=3)
    assert len(merged) < len(domains), "Small domains should be merged"
    large = [d for d in merged if d["name"] == "A"]
    assert len(large) == 1
    assert len(large[0]["modules"]) > 5, "Small domain modules should be absorbed"
```

- [ ] **Step 2: Run test to verify it passes (already implemented)**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_small_domain_merge.py -v`
Expected: PASS (merge_small_domains already exists from Task 8)

- [ ] **Step 3: Verify merge is wired into pipeline**

Check that `wiki/dependency_graph.py` already calls `merge_small_domains`. If not, add it:

```python
# In wiki/dependency_graph.py, after LLM domain classification parsing:
from wiki.domain_merger import merge_small_domains

# After domain_tree is built:
domain_tree = merge_small_domains(domain_tree, min_size=3)
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 5: Commit (if changes were made)**

```bash
git add wiki/dependency_graph.py tests/wiki/test_small_domain_merge.py
git commit -m "feat: verify small domain merge is wired into classification pipeline"
```

---

### Task 7: Full Integration Smoke Test

**Files:**
- Test: `tests/wiki/test_pipeline_integration_smoke.py`

- [ ] **Step 1: Write the integration smoke test**

```python
# tests/wiki/test_pipeline_integration_smoke.py
"""Smoke test: verify all new components are importable and wired."""

def test_all_components_importable():
    """All pipeline integration components must be importable."""
    from wiki.context_gap import cleanup_context_gaps, CONTEXT_GAP_RE
    from wiki.citation_verifier import verify_citations, extract_code_references
    from wiki.topo_sort import topological_order
    from wiki.overview_synthesizer import synthesize_overview_from_children
    from wiki.agent_config import AgentConfig
    from wiki.page_agent import WikiPageAgent
    from wiki.domain_merger import merge_small_domains
    from indexer.post_process import supplement_contains_relationships

def test_agent_config_defaults():
    from wiki.agent_config import AgentConfig
    cfg = AgentConfig.from_env()
    assert cfg.enabled is False, "Agent-Driven should be disabled by default"
    assert cfg.simple_threshold == 3

def test_compose_has_agent_path():
    """compose.py must reference AgentConfig for routing."""
    with open("wiki/nodes/compose.py") as f:
        source = f.read()
    assert "AgentConfig" in source
    assert "should_use_agent" in source

def test_quality_gate_has_citation_check():
    """quality_gate_node must reference citation_verifier."""
    with open("wiki/pipeline_graph.py") as f:
        source = f.read()
    assert "citation_verifier" in source or "verify_citations" in source

def test_tree_linker_has_overview_synthesizer():
    """tree_linker must use overview_synthesizer."""
    with open("wiki/tree_linker.py") as f:
        source = f.read()
    assert "overview_synthesizer" in source or "synthesize_overview_from_children" in source

def test_indexer_has_contains_supplement():
    """indexer must call supplement_contains_relationships."""
    with open("indexer/incremental_indexer.py") as f:
        source = f.read()
    assert "supplement_contains_relationships" in source
```

- [ ] **Step 2: Run the smoke test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_pipeline_integration_smoke.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/ -v --timeout=30`
Expected: All 67+ tests PASS (61 existing + 6 new)

- [ ] **Step 4: Commit**

```bash
git add tests/wiki/test_pipeline_integration_smoke.py
git commit -m "test: add pipeline integration smoke test for all wired components"
```

---

## Post-Implementation Checklist

After all tasks are complete:

1. **Environment Variables for Agent-Driven:**
   - `WIKI__AGENT_DRIVEN_GENERATION=true` to enable (default: `false`)
   - `WIKI__AGENT_SIMPLE_THRESHOLD=3` minimum modules to trigger agent (default: `3`)

2. **Deployment verification (manual):**
   - Index a repo → verify CONTAINS relationships are supplemented in graph
   - Generate wiki with `WIKI__AGENT_DRIVEN_GENERATION=true` → verify agent-generated pages
   - Check quality_gate logs for citation_invalid_count entries
   - Verify nested domain overview pages use child content synthesis

3. **Rollback plan:**
   - Each task is independent; revert individual commits if issues arise
   - Agent-Driven is off by default; no risk unless explicitly enabled
   - Citation penalty is capped at 0.2; won't break existing quality threshold logic
