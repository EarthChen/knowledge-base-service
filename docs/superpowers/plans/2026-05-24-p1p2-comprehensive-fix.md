# P1+P2 综合修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 11 correctness, performance, and frontend quality issues across wiki pipeline and dashboard.

**Architecture:** Three independent batches — Batch E (4 correctness fixes in quality_gate/heal/classify), Batch F (5 graph path + performance improvements), Batch G (2 frontend fixes). Each batch runs full regression after completion.

**Tech Stack:** Python 3.12+, FastAPI, pytest-asyncio, AsyncMock, React 19, TypeScript 5.9, Vitest

**Spec:** `docs/superpowers/specs/2026-05-24-heal-redesign-and-unified-llm-rate-control.md`

---

## Batch E: 正确性修复

### Task E-2: 错误占位页排除治愈

**Files:**
- Modify: `wiki/nodes/quality_gate.py` (~L92)
- Test: `tests/wiki/nodes/test_quality_gate.py` (new or append)

- [ ] **Step 1: Write the failing test**

Create `tests/wiki/nodes/test_quality_gate_agent_error.py`:

```python
"""Test that agent_error pages are excluded from healing."""
from __future__ import annotations

import pytest
from wiki.nodes.quality_gate import quality_gate_node


@pytest.mark.asyncio
async def test_agent_error_pages_excluded_from_healing(monkeypatch):
    """Pages with generation_mode=agent_error should NOT enter pages_to_heal."""
    monkeypatch.setattr("wiki.nodes.quality_gate.get_settings", lambda: type("S", (), {"wiki": type("W", (), {"quality_gate_levels": "L1", "heal_l2_threshold": 0.0})()})())

    error_page = {
        "path": "/wiki/broken-domain",
        "title": "Broken Domain",
        "page_type": "topic",
        "content": "Error generating page",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "agent_error"},
    }
    state = {
        "pages": [error_page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }
    result = await quality_gate_node(state, {"configurable": {}})
    assert "/wiki/broken-domain" not in result.get("pages_to_heal", [])
    scores = result.get("quality_scores", {})
    assert scores.get("/wiki/broken-domain", {}).get("skipped_reason") == "agent_error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate_agent_error.py -x -v`
Expected: FAIL (no skipped_reason logic exists yet)

- [ ] **Step 3: Implement — add agent_error skip in quality_gate_node**

In `wiki/nodes/quality_gate.py`, inside the `for page_dict in state.get("pages", []):` loop, before the `try: page = WikiPage.from_dict(page_dict)` block, add:

```python
        gen_mode = page_dict.get("metadata", {}).get("generation_mode", "")
        if gen_mode == "agent_error":
            page_path = page_dict.get("path", "")
            quality_scores[page_path] = {
                "l1_structural": 0.0,
                "overall": 0.0,
                "skipped_reason": "agent_error",
            }
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate_agent_error.py -x -v`
Expected: PASS

---

### Task E-1: Heal 计数器分离

**Files:**
- Modify: `wiki/nodes/heal.py` (return heal_cycles)
- Modify: `wiki/nodes/quality_gate.py` (use heal_cycles instead of heal_attempts)
- Test: `tests/wiki/nodes/test_heal_cycles.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/wiki/nodes/test_heal_cycles.py`:

```python
"""Test heal_cycles vs heal_attempts separation."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.nodes.quality_gate import quality_gate_node


@pytest.mark.asyncio
async def test_quality_gate_uses_heal_cycles_not_attempts():
    """quality_gate should use heal_cycles (outer loop count) not heal_attempts (inner round count)."""
    page = {
        "path": "/wiki/test-page",
        "title": "Test Page",
        "page_type": "topic",
        "content": "short",  # will fail L1
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [page],
        "heal_attempts": {"/wiki/test-page": 5},  # inner rounds exhausted
        "heal_cycles": {"/wiki/test-page": 0},     # outer loop NOT yet run
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1"
        wiki_cfg.heal_l2_threshold = 0.0
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    # Page should be scheduled for heal because heal_cycles=0 < max_retries=2
    # even though heal_attempts=5
    assert "/wiki/test-page" in result.get("pages_to_heal", [])


@pytest.mark.asyncio
async def test_quality_gate_blocks_heal_after_cycles_exhausted():
    """quality_gate should NOT schedule heal when heal_cycles >= max_retries."""
    page = {
        "path": "/wiki/test-page",
        "title": "Test Page",
        "page_type": "topic",
        "content": "short",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [page],
        "heal_attempts": {"/wiki/test-page": 5},
        "heal_cycles": {"/wiki/test-page": 3},  # exhausted
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1"
        wiki_cfg.heal_l2_threshold = 0.0
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    assert "/wiki/test-page" not in result.get("pages_to_heal", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/nodes/test_heal_cycles.py -x -v`
Expected: FAIL (quality_gate still uses heal_attempts)

- [ ] **Step 3: Implement — modify quality_gate to use heal_cycles**

In `wiki/nodes/quality_gate.py`:
1. Add at function start: `heal_cycles: dict[str, int] = dict(state.get("heal_cycles", {}))`
2. Change L162: `attempts = heal_attempts.get(page.path, 0)` → `cycles = heal_cycles.get(page.path, 0)`
3. Change L165: `if structural_score < threshold and attempts < max_retries:` → `if structural_score < threshold and cycles < max_retries:`

- [ ] **Step 4: Implement — heal_pages_node returns heal_cycles**

In `wiki/nodes/heal.py`:
1. Add at L181: `heal_cycles: dict[str, int] = dict(state.get("heal_cycles", {}))`
2. Before return at end: increment cycles for all processed pages:
   ```python
   for p in initial_paths:
       heal_cycles[p] = heal_cycles.get(p, 0) + 1
   ```
3. Add `"heal_cycles": heal_cycles` to return dict

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/wiki/nodes/test_heal_cycles.py tests/wiki/nodes/test_quality_gate_agent_error.py -x -v`
Expected: ALL PASS

---

### Task E-3: L2 纳入治愈决策

**Files:**
- Modify: `core/config.py` (add heal_l2_threshold)
- Modify: `wiki/nodes/quality_gate.py` (L2 condition)
- Test: `tests/wiki/nodes/test_quality_gate_l2_heal.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/wiki/nodes/test_quality_gate_l2_heal.py`:

```python
"""Test L2-driven healing in quality_gate."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from wiki.nodes.quality_gate import quality_gate_node


@pytest.mark.asyncio
async def test_l2_below_threshold_triggers_heal():
    """Page passing L1 but failing L2 should be scheduled for heal when heal_l2_threshold > 0."""
    # Page with good structure (passes L1 ≥ 0.7) but poor depth
    good_structure_page = {
        "path": "/wiki/shallow-page",
        "title": "Shallow Page",
        "page_type": "topic",
        "content": (
            "## Overview\n"
            + "x" * 250
            + "\n## Key components\nCore\n## Relationships\n- [[peer]]\n"
        ),
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [good_structure_page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1,L2"
        wiki_cfg.heal_l2_threshold = 0.55
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    scores = result.get("quality_scores", {}).get("/wiki/shallow-page", {})
    # If L1 passed (>= 0.7) but L2 < 0.55, page should be in pages_to_heal
    l1 = scores.get("l1_structural", 0)
    l2 = scores.get("l2_bench", 1.0)
    if l1 >= 0.7 and l2 < 0.55:
        assert "/wiki/shallow-page" in result.get("pages_to_heal", [])


@pytest.mark.asyncio
async def test_l2_threshold_zero_preserves_existing_behavior():
    """When heal_l2_threshold=0, L2 should NOT affect heal decisions."""
    page = {
        "path": "/wiki/ok-page",
        "title": "OK Page",
        "page_type": "topic",
        "content": (
            "## Overview\n"
            + "x" * 250
            + "\n## Key components\nCore\n## Relationships\n- [[peer]]\n"
        ),
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1,L2"
        wiki_cfg.heal_l2_threshold = 0.0  # disabled
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    scores = result.get("quality_scores", {}).get("/wiki/ok-page", {})
    l1 = scores.get("l1_structural", 0)
    if l1 >= 0.7:
        # Should NOT be in pages_to_heal regardless of L2
        assert "/wiki/ok-page" not in result.get("pages_to_heal", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate_l2_heal.py -x -v`
Expected: FAIL

- [ ] **Step 3: Implement**

1. In `core/config.py`, `AppWikiFlags` class, add:
   ```python
   heal_l2_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
   ```

2. In `wiki/nodes/quality_gate.py`, after computing `structural_score` (around L164), add L2 check:
   ```python
   l2_val = score_dict.get("l2_bench", 1.0)
   l2_below = (l2_val < wiki_cfg.heal_l2_threshold) if wiki_cfg.heal_l2_threshold > 0 and "L2" in levels else False
   if (structural_score < threshold or l2_below) and cycles < max_retries:
       pages_to_heal.append(page.path)
   ```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate_l2_heal.py tests/wiki/nodes/test_heal_cycles.py tests/wiki/nodes/test_quality_gate_agent_error.py -x -v`
Expected: ALL PASS

---

### Task E-4: SUPPORTING 角色收窄

**Files:**
- Modify: `core/config.py` (add classify_include_supporting)
- Modify: `wiki/nodes/graph_domain_decompose.py` (~L456)
- Test: `tests/wiki/nodes/test_supporting_role_filter.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/wiki/nodes/test_supporting_role_filter.py`:

```python
"""Test SUPPORTING role exclusion from domain classification."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from wiki.entity_role_classifier import WikiEntityRole


def test_supporting_excluded_when_config_disabled():
    """When classify_include_supporting=False, SUPPORTING modules excluded from biz_modules."""
    from wiki.nodes.graph_domain_decompose import _filter_biz_modules

    entity_roles = {
        "uid1": WikiEntityRole.HAS_BUSINESS_LOGIC,
        "uid2": WikiEntityRole.SUPPORTING,
        "uid3": WikiEntityRole.DATA_MODEL,
    }
    modules = {
        "repo1": [
            {"uid": "uid1", "properties": {"name": "OrderService", "path": "order/service.py"}},
            {"uid": "uid2", "properties": {"name": "StringHelper", "path": "util/string.py"}},
            {"uid": "uid3", "properties": {"name": "OrderModel", "path": "order/model.py"}},
        ]
    }

    with patch("wiki.nodes.graph_domain_decompose.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.classify_include_supporting = False
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        biz, supporting_excluded = _filter_biz_modules(entity_roles, modules)

    biz_names = [name for _, name in biz]
    assert "OrderService" in biz_names
    assert "StringHelper" not in biz_names
    assert "OrderModel" not in biz_names
    assert "StringHelper" in [name for _, name in supporting_excluded]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/nodes/test_supporting_role_filter.py -x -v`
Expected: FAIL (_filter_biz_modules doesn't exist yet)

- [ ] **Step 3: Implement**

1. In `core/config.py`, `AppWikiFlags` class, add:
   ```python
   classify_include_supporting: bool = Field(default=True)
   ```

2. In `wiki/nodes/graph_domain_decompose.py`, extract a `_filter_biz_modules()` helper from the existing biz_modules filtering logic (~L436-463):
   ```python
   def _filter_biz_modules(
       entity_roles: dict[str, str],
       modules: dict[str, list[dict]],
   ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
       """Return (biz_modules, supporting_excluded)."""
       from core.config import get_settings
       wiki_cfg = get_settings().wiki
       
       allowed_roles = set(DOMAIN_CLASSIFICATION_ENTITY_ROLES)
       if not wiki_cfg.classify_include_supporting:
           allowed_roles.discard(WikiEntityRole.SUPPORTING)
       
       biz_modules: list[tuple[str, str]] = []
       supporting_excluded: list[tuple[str, str]] = []
       
       for repo, mod_list in modules.items():
           for mod_dict in mod_list:
               uid = mod_dict.get("uid", "")
               props = mod_dict.get("properties", {})
               name = str(props.get("name", ""))
               role_str = str(entity_roles.get(uid, ""))
               try:
                   role = WikiEntityRole(role_str)
               except ValueError:
                   continue
               if role in allowed_roles:
                   biz_modules.append((repo, name))
               elif role == WikiEntityRole.SUPPORTING and not wiki_cfg.classify_include_supporting:
                   supporting_excluded.append((repo, name))
       
       return biz_modules, supporting_excluded
   ```

3. Replace inline filtering in `graph_driven_domain_decompose_node` with `_filter_biz_modules()` call.

4. After main clustering, route `supporting_excluded` modules to nearest domain via call edges or embedding distance.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/nodes/test_supporting_role_filter.py -x -v`
Expected: PASS

- [ ] **Step 5: Run full Batch E regression**

Run: `uv run pytest tests/wiki/ --no-cov -q`
Expected: 2930+ passed

---

## Batch F: 图路径 + 性能

_(Tasks F-3 → F-1 → F-2 → F-4 → F-5 — 详见 spec)_

### Task F-3: 模块复合键索引

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py` (L441-454, key change)
- Modify: `wiki/nodes/domain_compose.py` (L51-67, dual index)
- Test: `tests/wiki/nodes/test_compound_key_index.py`

- [ ] **Step 1: Write failing test** — multi-repo same-name modules produce distinct entries
- [ ] **Step 2: Run to verify fail**
- [ ] **Step 3: Change dict keys to `f"{repo}|{name}"` compound key**
- [ ] **Step 4: Add name-fallback in domain_compose `_module_dict_by_name`**
- [ ] **Step 5: Run test to verify pass**

### Task F-1: 图路径增量语义

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py` (main function)
- Modify: `wiki/service.py` (inject existing_domain_mapping)
- Test: `tests/wiki/nodes/test_graph_incremental.py`

- [ ] **Step 1: Write failing test** — incremental mode preserves unchanged domains
- [ ] **Step 2: Run to verify fail**
- [ ] **Step 3: Implement F-1a: read existing_domain_mapping, split changed/unchanged**
- [ ] **Step 4: Implement F-1b: assign changed modules to nearest centroid**
- [ ] **Step 5: Implement F-1c: compute affected_domains from changed modules only**
- [ ] **Step 6: Run test to verify pass**

### Task F-2: 图路径 anchor/pinned 支持

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py`
- Test: `tests/wiki/nodes/test_pinned_modules.py`

- [ ] **Step 1: Write failing test** — pinned modules forced to specified domain
- [ ] **Step 2: Run to verify fail**
- [ ] **Step 3: Remove pinned from clustering candidates; force-assign after clustering**
- [ ] **Step 4: Run test to verify pass**

### Task F-4: Parent pages 并行化

**Files:**
- Modify: `wiki/nodes/aggregate.py` (L163-313)
- Test: `tests/wiki/nodes/test_parent_parallel.py`

- [ ] **Step 1: Write failing test** — parallel produces same result as serial
- [ ] **Step 2: Run to verify fail**
- [ ] **Step 3: Extract `_compose_one_parent()`, wrap in gather with semaphore**
- [ ] **Step 4: Run test to verify pass**

### Task F-5: DomainDocAgent 迭代缩减

**Files:**
- Modify: `core/config.py` (add domain_agent_early_exit_quality)
- Modify: `wiki/domain_doc_agent.py` (~L560)
- Test: `tests/wiki/test_domain_agent_early_exit.py`

- [ ] **Step 1: Write failing test** — agent exits early when quality >= threshold
- [ ] **Step 2: Run to verify fail**
- [ ] **Step 3: Add early exit condition after evaluate_quality**
- [ ] **Step 4: Run test to verify pass**
- [ ] **Step 5: Run full Batch F regression**: `uv run pytest tests/wiki/ --no-cov -q`

---

## Batch G: 前端

### Task G-1: Toast a11y 修复

**Files:**
- Modify: `dashboard/src/components/ui/Toast.tsx`
- Modify: `dashboard/src/i18n/en.ts`
- Modify: `dashboard/src/i18n/zh.ts`
- Test: existing vitest or manual

- [ ] **Step 1: Add `role="status"` and `aria-live="polite"` to Toast container**
- [ ] **Step 2: Add i18n keys for dismiss label**
- [ ] **Step 3: Replace hardcoded dismiss label with i18n key**
- [ ] **Step 4: Run**: `cd dashboard && pnpm test && pnpm lint`

### Task G-3: WikiShell/GraphExplorer 组件拆分

**Files:**
- Split: `dashboard/src/pages/WikiShell.tsx` → 4 files
- Split: `dashboard/src/pages/GraphExplorer.tsx` → 4 files
- Test: existing tests must still pass

- [ ] **Step 1: Extract WikiDomainDialogs from WikiShell**
- [ ] **Step 2: Extract useWikiSSE hook from WikiShell**
- [ ] **Step 3: Extract WikiSidebarLayout from WikiShell**
- [ ] **Step 4: Extract useGraphData hook from GraphExplorer**
- [ ] **Step 5: Extract useGraphControls hook from GraphExplorer**
- [ ] **Step 6: Extract GraphNodeDetail from GraphExplorer**
- [ ] **Step 7: Consolidate dark mode to useIsDarkMode**
- [ ] **Step 8: Run**: `cd dashboard && pnpm test && pnpm lint && pnpm build`
- [ ] **Step 9: Run full regression**: `uv run pytest tests/wiki/ --no-cov -q`
