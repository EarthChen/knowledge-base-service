# Domain Theme Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-driven bottom-up recursive domain aggregation to group semantically related domains under parent domains.

**Architecture:** After decompose produces a flat/shallow domain tree, a new aggregation step recursively scans siblings bottom-up, calls LLM to identify thematic groups, and constructs parent domain nodes. User-edited domains are respected, batch processing includes cross-batch consolidation, and duplicate parent domains are auto-merged.

**Tech Stack:** Python 3.11+, LangGraph pipeline, FalkorDB graph, FastAPI

**Spec:** `docs/superpowers/specs/20260518_105505_domain-theme-aggregation.md`

---

### Task 1: Modify Decompose Prompt

**Files:**
- Modify: `wiki/dependency_graph.py:328-331`

- [ ] **Step 1: Modify the prompt constraint**

In `wiki/dependency_graph.py`, method `_build_decomposition_prompt`, replace:

```python
            f"- Prefer flatter trees when modules are loosely related\n\n"
```

with:

```python
            f"- When multiple domains share a common business theme "
            f"(e.g. '家族核心管理', '家族任务系统'), group them under a parent domain "
            f"named by the shared theme (e.g. '家族')\n"
            f"- Only keep domains flat when they are genuinely unrelated\n\n"
```

- [ ] **Step 2: Verify no tests break**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_domain_planning_nodes.py tests/wiki/test_domain_dedup.py -v --timeout=30 2>&1 | tail -20`
Expected: All existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/dependency_graph.py
git commit -m "feat(wiki): update decompose prompt to encourage thematic grouping"
```

---

### Task 2: Add `aggregate_domains_recursive` and helpers

**Files:**
- Modify: `wiki/domain_merger.py`
- Create: `tests/wiki/test_domain_theme_aggregation.py`

- [ ] **Step 1: Write failing tests for `_parse_aggregation_result`**

Create `tests/wiki/test_domain_theme_aggregation.py`:

```python
"""Tests for domain theme aggregation."""
from __future__ import annotations

import pytest

from wiki.domain_merger import _parse_aggregation_result


def _make_node(name: str, display_name: str = "", modules: list | None = None, children: list | None = None) -> dict:
    return {
        "name": name,
        "display_name": display_name or name,
        "description": "",
        "modules": modules or [],
        "children": children or [],
    }


class TestParseAggregationResult:
    def test_valid_new_groups(self):
        nodes = [
            _make_node("family-core", "家族核心管理"),
            _make_node("family-task", "家族任务系统"),
            _make_node("gift-order", "礼物订单"),
        ]
        response = '{"new_groups": [{"parent_display_name": "家族", "parent_slug": "family", "children_slugs": ["family-core", "family-task"]}], "assign_to_existing": {}, "standalone_slugs": ["gift-order"]}'
        groups, assigns, standalones = _parse_aggregation_result(response, nodes)
        assert len(groups) == 1
        assert groups[0]["parent_slug"] == "family"
        assert set(groups[0]["children_slugs"]) == {"family-core", "family-task"}
        assert standalones == ["gift-order"]

    def test_assign_to_existing(self):
        nodes = [
            _make_node("family-task", "家族任务系统"),
            _make_node("gift-order", "礼物订单"),
        ]
        response = '{"new_groups": [], "assign_to_existing": {"family": ["family-task"]}, "standalone_slugs": ["gift-order"]}'
        groups, assigns, standalones = _parse_aggregation_result(response, nodes)
        assert len(groups) == 0
        assert assigns == {"family": ["family-task"]}

    def test_invalid_json_returns_empty(self):
        nodes = [_make_node("a", "A")]
        groups, assigns, standalones = _parse_aggregation_result("not json", nodes)
        assert groups == []
        assert assigns == {}
        assert standalones == []

    def test_unknown_slug_ignored(self):
        nodes = [_make_node("family-core", "家族核心管理")]
        response = '{"new_groups": [{"parent_display_name": "家族", "parent_slug": "family", "children_slugs": ["family-core", "nonexistent"]}], "assign_to_existing": {}, "standalone_slugs": []}'
        groups, assigns, standalones = _parse_aggregation_result(response, nodes)
        assert groups[0]["children_slugs"] == ["family-core"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/wiki/test_domain_theme_aggregation.py -v 2>&1 | tail -20`
Expected: FAIL with `ImportError` (function not defined yet)

- [ ] **Step 3: Implement `_parse_aggregation_result`**

In `wiki/domain_merger.py`, add after the existing `merge_small_domains` function:

```python
import json
import re
from typing import Any


def _parse_aggregation_result(
    response: str,
    nodes: list[dict],
) -> tuple[list[dict], dict[str, list[str]], list[str]]:
    """Parse LLM aggregation response.

    Returns:
        (new_groups, assign_to_existing, standalone_slugs)
        new_groups: list of {"parent_display_name", "parent_slug", "children_slugs"}
        assign_to_existing: {existing_parent_slug: [child_slugs]}
        standalone_slugs: list of slug strings
    """
    valid_slugs = {n.get("name", "") for n in nodes}

    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.warning("aggregate_parse_failed", response_len=len(response))
        return [], {}, []

    new_groups: list[dict] = []
    for g in data.get("new_groups", []):
        children = [s for s in g.get("children_slugs", []) if s in valid_slugs]
        if len(children) >= 2:
            new_groups.append({
                "parent_display_name": g.get("parent_display_name", ""),
                "parent_slug": g.get("parent_slug", ""),
                "children_slugs": children,
            })

    assigns: dict[str, list[str]] = {}
    for parent_slug, children in data.get("assign_to_existing", {}).items():
        valid_children = [s for s in children if s in valid_slugs]
        if valid_children:
            assigns[parent_slug] = valid_children

    standalones = [s for s in data.get("standalone_slugs", []) if s in valid_slugs]

    return new_groups, assigns, standalones
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/wiki/test_domain_theme_aggregation.py::TestParseAggregationResult -v 2>&1 | tail -20`
Expected: All 4 tests PASS

- [ ] **Step 5: Write failing tests for `_apply_aggregation` and `_tree_depth`**

Append to `tests/wiki/test_domain_theme_aggregation.py`:

```python
from wiki.domain_merger import _apply_aggregation, _tree_depth


class TestTreeDepth:
    def test_flat_tree(self):
        nodes = [_make_node("a"), _make_node("b")]
        assert _tree_depth(nodes) == 1

    def test_nested_tree(self):
        child = _make_node("c")
        parent = _make_node("p", children=[child])
        assert _tree_depth([parent]) == 2

    def test_empty(self):
        assert _tree_depth([]) == 0


class TestApplyAggregation:
    def test_creates_parent_with_children(self):
        nodes = [
            _make_node("family-core", "家族核心管理", modules=["m1"]),
            _make_node("family-task", "家族任务系统", modules=["m2"]),
            _make_node("gift-order", "礼物订单", modules=["m3"]),
        ]
        groups = [{"parent_display_name": "家族", "parent_slug": "family", "children_slugs": ["family-core", "family-task"]}]
        result = _apply_aggregation(nodes, groups, {})
        parent_names = [n["name"] for n in result]
        assert "family" in parent_names
        family = next(n for n in result if n["name"] == "family")
        assert len(family["children"]) == 2
        assert family["modules"] == []
        assert "gift-order" in parent_names

    def test_assign_to_existing_parent(self):
        existing_parent = _make_node("family", "家族", children=[_make_node("family-core", "家族核心管理")])
        orphan = _make_node("family-task", "家族任务系统", modules=["m2"])
        nodes = [existing_parent, orphan]
        assigns = {"family": ["family-task"]}
        result = _apply_aggregation(nodes, [], assigns)
        family = next(n for n in result if n["name"] == "family")
        assert len(family["children"]) == 2

    def test_dedup_new_group_with_existing(self):
        existing_parent = _make_node("family", "家族", children=[_make_node("family-core", "家族核心管理")])
        orphan1 = _make_node("family-task", "家族任务系统")
        orphan2 = _make_node("family-combat", "家族战力")
        nodes = [existing_parent, orphan1, orphan2]
        groups = [{"parent_display_name": "家族", "parent_slug": "family", "children_slugs": ["family-task", "family-combat"]}]
        result = _apply_aggregation(nodes, groups, {})
        family_nodes = [n for n in result if n["name"] == "family"]
        assert len(family_nodes) == 1
        assert len(family_nodes[0]["children"]) == 3
```

- [ ] **Step 6: Implement `_tree_depth` and `_apply_aggregation`**

In `wiki/domain_merger.py`, add:

```python
def _tree_depth(nodes: list[dict]) -> int:
    """Calculate the maximum depth of a domain tree."""
    if not nodes:
        return 0
    return 1 + max((_tree_depth(n.get("children", [])) for n in nodes), default=0)


def _apply_aggregation(
    nodes: list[dict],
    new_groups: list[dict],
    assign_to_existing: dict[str, list[str]],
) -> list[dict]:
    """Apply aggregation results: create parent nodes and assign orphans."""
    slug_to_node = {n.get("name", ""): n for n in nodes}
    used_slugs: set[str] = set()
    result: list[dict] = []

    existing_parents = {
        n.get("name", ""): n for n in nodes if n.get("children")
    }

    for assigns_parent, child_slugs in assign_to_existing.items():
        parent = existing_parents.get(assigns_parent)
        if parent:
            for cs in child_slugs:
                child = slug_to_node.get(cs)
                if child and cs not in used_slugs:
                    parent.setdefault("children", []).append(child)
                    used_slugs.add(cs)

    for group in new_groups:
        parent_slug = group["parent_slug"]
        children_slugs = group["children_slugs"]

        if parent_slug in existing_parents:
            parent = existing_parents[parent_slug]
            for cs in children_slugs:
                child = slug_to_node.get(cs)
                if child and cs not in used_slugs:
                    parent.setdefault("children", []).append(child)
                    used_slugs.add(cs)
        else:
            children = []
            for cs in children_slugs:
                child = slug_to_node.get(cs)
                if child and cs not in used_slugs:
                    children.append(child)
                    used_slugs.add(cs)
            if len(children) >= 2:
                from wiki.path_conventions import normalize_slug
                parent_node = {
                    "name": normalize_slug(parent_slug) or parent_slug,
                    "display_name": group["parent_display_name"],
                    "description": "",
                    "modules": [],
                    "children": children,
                }
                result.append(parent_node)

    for node in nodes:
        slug = node.get("name", "")
        if slug not in used_slugs:
            result.append(node)

    return result
```

- [ ] **Step 7: Run all tests**

Run: `python -m pytest tests/wiki/test_domain_theme_aggregation.py -v 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 8: Write failing test for `_build_aggregation_prompt`**

Append to `tests/wiki/test_domain_theme_aggregation.py`:

```python
from wiki.domain_merger import _build_aggregation_prompt


class TestBuildAggregationPrompt:
    def test_includes_domain_info(self):
        nodes = [_make_node("family-core", "家族核心管理", modules=["m1", "m2"])]
        prompt = _build_aggregation_prompt(nodes, [])
        assert "家族核心管理" in prompt
        assert "family-core" in prompt

    def test_includes_existing_parents(self):
        nodes = [_make_node("gift-order", "礼物订单")]
        existing = [{"slug": "family", "display_name": "家族", "children": ["家族核心管理"]}]
        prompt = _build_aggregation_prompt(nodes, existing)
        assert "家族" in prompt
        assert "已有父域" in prompt or "existing" in prompt.lower()
```

- [ ] **Step 9: Implement `_build_aggregation_prompt`**

In `wiki/domain_merger.py`, add:

```python
def _build_aggregation_prompt(
    nodes: list[dict],
    existing_parents: list[dict],
) -> str:
    """Build LLM prompt for domain theme aggregation."""
    domain_info = [
        {
            "slug": d.get("name", ""),
            "display_name": d.get("display_name", ""),
            "description": d.get("description", ""),
            "module_count": len(d.get("modules", [])),
            "child_count": len(d.get("children", [])),
        }
        for d in nodes
    ]

    existing_section = ""
    if existing_parents:
        existing_section = (
            "\n已有父域结构（请优先将相关域归入已有父域，而非创建同名新组）：\n"
            + json.dumps(existing_parents, ensure_ascii=False, indent=2)
            + "\n"
        )

    return (
        f"以下是一个代码仓库中自动发现的 {len(nodes)} 个业务域。\n"
        "请分析这些域之间的语义关系，将属于同一业务主题的域分组到父域下。\n\n"
        "规则：\n"
        "1. 只有真正属于同一业务主题的域才应聚合\n"
        "   例如：\"家族核心管理\"、\"家族任务系统\"、\"家族战力\" → 父域 \"家族\"\n"
        "2. 不相关的域保持独立（标记为 standalone）\n"
        "3. 每个父域至少包含 2 个子域\n"
        "4. 父域名为简短的中文业务主题名\n"
        "5. 每个域只能属于一个组\n"
        "6. 不要过度聚合——只聚合明确相关的域\n"
        "7. 如果不确定某个域是否属于某组，标记为 standalone\n\n"
        f"{existing_section}\n"
        f"待分组的域列表：\n{json.dumps(domain_info, ensure_ascii=False, indent=2)}\n\n"
        "返回 JSON：\n"
        '{"new_groups": [{"parent_display_name": "家族", "parent_slug": "family", '
        '"children_slugs": ["family-core", "family-task"]}], '
        '"assign_to_existing": {"family": ["family-task"]}, '
        '"standalone_slugs": ["gift-order"]}\n'
        "其中 assign_to_existing 将域归入已有父域（key 为已有父域的 slug）。"
    )
```

- [ ] **Step 10: Run tests**

Run: `python -m pytest tests/wiki/test_domain_theme_aggregation.py -v 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 11: Write failing test for `aggregate_domains_recursive`**

Append to `tests/wiki/test_domain_theme_aggregation.py`:

```python
import asyncio
from unittest.mock import AsyncMock

from wiki.domain_merger import aggregate_domains_recursive


class TestAggregateDomainRecursive:
    def test_skips_small_sibling_count(self):
        nodes = [_make_node("a"), _make_node("b")]
        llm = AsyncMock()
        result = asyncio.get_event_loop().run_until_complete(
            aggregate_domains_recursive(nodes, llm)
        )
        assert result == nodes
        llm.generate.assert_not_called()

    def test_groups_siblings_by_theme(self):
        nodes = [
            _make_node("family-core", "家族核心管理", modules=["m1"]),
            _make_node("family-task", "家族任务系统", modules=["m2"]),
            _make_node("family-combat", "家族战力", modules=["m3"]),
            _make_node("gift-order", "礼物订单", modules=["m4"]),
        ]
        llm = AsyncMock()
        llm.generate.return_value = json.dumps({
            "new_groups": [
                {"parent_display_name": "家族", "parent_slug": "family",
                 "children_slugs": ["family-core", "family-task", "family-combat"]}
            ],
            "assign_to_existing": {},
            "standalone_slugs": ["gift-order"],
        })
        result = asyncio.get_event_loop().run_until_complete(
            aggregate_domains_recursive(nodes, llm)
        )
        names = [n["name"] for n in result]
        assert "family" in names
        assert "gift-order" in names
        family = next(n for n in result if n["name"] == "family")
        assert len(family["children"]) == 3

    def test_skips_user_edited_domains(self):
        nodes = [
            _make_node("family-core", "家族核心管理"),
            _make_node("family-task", "家族任务系统"),
            _make_node("family-combat", "家族战力"),
            _make_node("gift-order", "礼物订单"),
        ]
        nodes[0]["user_edited"] = True
        llm = AsyncMock()
        llm.generate.return_value = json.dumps({
            "new_groups": [
                {"parent_display_name": "家族", "parent_slug": "family",
                 "children_slugs": ["family-task", "family-combat"]}
            ],
            "assign_to_existing": {},
            "standalone_slugs": ["gift-order"],
        })
        result = asyncio.get_event_loop().run_until_complete(
            aggregate_domains_recursive(nodes, llm)
        )
        top_names = [n["name"] for n in result]
        assert "family-core" in top_names

    def test_llm_failure_preserves_original(self):
        nodes = [
            _make_node("a", modules=["m1"]),
            _make_node("b", modules=["m2"]),
            _make_node("c", modules=["m3"]),
        ]
        llm = AsyncMock()
        llm.generate.side_effect = RuntimeError("LLM down")
        result = asyncio.get_event_loop().run_until_complete(
            aggregate_domains_recursive(nodes, llm)
        )
        assert len(result) == 3

    def test_depth_limit_prevents_aggregation(self):
        nodes = [_make_node("a"), _make_node("b"), _make_node("c")]
        llm = AsyncMock()
        result = asyncio.get_event_loop().run_until_complete(
            aggregate_domains_recursive(nodes, llm, max_tree_depth=1)
        )
        assert len(result) == 3
        llm.generate.assert_not_called()
```

- [ ] **Step 12: Implement `aggregate_domains_recursive` and `_aggregate_siblings_by_theme`**

In `wiki/domain_merger.py`, add:

```python
from wiki.prompts import SYSTEM_JSON_ONLY

_BATCH_SIZE = 25


async def aggregate_domains_recursive(
    nodes: list[dict],
    llm: Any,
    *,
    current_depth: int = 0,
    max_tree_depth: int = 5,
    min_siblings: int = 3,
) -> list[dict]:
    """Bottom-up recursive aggregation of semantically related domains."""
    if _tree_depth(nodes) >= max_tree_depth:
        return nodes

    for node in nodes:
        children = node.get("children", [])
        if children and len(children) >= min_siblings:
            node["children"] = await aggregate_domains_recursive(
                children, llm,
                current_depth=current_depth + 1,
                max_tree_depth=max_tree_depth,
                min_siblings=min_siblings,
            )

    if len(nodes) >= min_siblings:
        try:
            nodes = await _aggregate_siblings_by_theme(nodes, llm, max_tree_depth)
        except Exception:
            log.warning("aggregate_theme_failed", depth=current_depth, exc_info=True)

    return nodes


async def _aggregate_siblings_by_theme(
    nodes: list[dict],
    llm: Any,
    max_tree_depth: int,
) -> list[dict]:
    """Single-level aggregation: call LLM to group siblings by theme."""
    aggregable = [n for n in nodes if not n.get("user_edited")]
    protected = [n for n in nodes if n.get("user_edited")]

    if len(aggregable) < 3:
        return nodes

    existing_parents = [
        {
            "slug": n.get("name", ""),
            "display_name": n.get("display_name", ""),
            "children": [c.get("display_name", c.get("name", "")) for c in n.get("children", [])],
        }
        for n in nodes if n.get("children")
    ]

    if len(aggregable) <= _BATCH_SIZE:
        all_groups, all_assigns = await _single_aggregate_batch(
            aggregable, existing_parents, llm
        )
    else:
        all_groups, all_assigns = await _batched_aggregate(
            aggregable, existing_parents, llm
        )

    if not all_groups and not all_assigns:
        return nodes

    result = _apply_aggregation(nodes, all_groups, all_assigns)

    if _tree_depth(result) > max_tree_depth:
        log.info("aggregate_theme_skipped_depth", depth=_tree_depth(result), max=max_tree_depth)
        return nodes

    log.info("aggregate_theme_applied", groups=len(all_groups), assigns=len(all_assigns))
    return result


async def _single_aggregate_batch(
    nodes: list[dict],
    existing_parents: list[dict],
    llm: Any,
) -> tuple[list[dict], dict[str, list[str]]]:
    prompt = _build_aggregation_prompt(nodes, existing_parents)
    response = await llm.generate(prompt, system=SYSTEM_JSON_ONLY)
    groups, assigns, _ = _parse_aggregation_result(response, nodes)
    return groups, assigns


async def _batched_aggregate(
    nodes: list[dict],
    existing_parents: list[dict],
    llm: Any,
) -> tuple[list[dict], dict[str, list[str]]]:
    """Process in batches, then consolidate."""
    all_groups: list[dict] = []
    all_assigns: dict[str, list[str]] = {}
    all_standalones: list[dict] = []

    for i in range(0, len(nodes), _BATCH_SIZE):
        batch = nodes[i : i + _BATCH_SIZE]
        prompt = _build_aggregation_prompt(batch, existing_parents)
        try:
            response = await llm.generate(prompt, system=SYSTEM_JSON_ONLY)
            groups, assigns, standalone_slugs = _parse_aggregation_result(response, batch)
            all_groups.extend(groups)
            for k, v in assigns.items():
                all_assigns.setdefault(k, []).extend(v)
            standalone_nodes = [n for n in batch if n.get("name", "") in set(standalone_slugs)]
            all_standalones.extend(standalone_nodes)
        except Exception:
            log.warning("aggregate_batch_failed", batch_index=i, exc_info=True)
            all_standalones.extend(batch)

    if all_standalones and all_groups:
        consolidated_existing = existing_parents + [
            {"slug": g["parent_slug"], "display_name": g["parent_display_name"], "children": g["children_slugs"]}
            for g in all_groups
        ]
        try:
            prompt = _build_aggregation_prompt(all_standalones, consolidated_existing)
            response = await llm.generate(prompt, system=SYSTEM_JSON_ONLY)
            extra_groups, extra_assigns, _ = _parse_aggregation_result(response, all_standalones)
            all_groups.extend(extra_groups)
            for k, v in extra_assigns.items():
                all_assigns.setdefault(k, []).extend(v)
        except Exception:
            log.warning("aggregate_consolidation_failed", exc_info=True)

    return all_groups, all_assigns
```

- [ ] **Step 13: Run all tests**

Run: `python -m pytest tests/wiki/test_domain_theme_aggregation.py -v 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 14: Commit**

```bash
git add wiki/domain_merger.py tests/wiki/test_domain_theme_aggregation.py
git commit -m "feat(wiki): add LLM-driven recursive domain theme aggregation"
```

---

### Task 3: Integrate into `decompose_hierarchy_node`

**Files:**
- Modify: `wiki/nodes/classify.py:513-540`

- [ ] **Step 1: Add import and call**

In `wiki/nodes/classify.py`, after the import block (around line 23), add:

```python
from wiki.domain_merger import aggregate_domains_recursive
```

Then in `decompose_hierarchy_node`, after `_assign_slugs_to_tree(domain_tree, domain_mapping, domain_display_names)` (line 513) and before the `oversized = _detect_oversized_leaves(domain_tree)` block (line 516), add:

```python
    if llm and domain_tree and len(domain_tree) >= 3:
        try:
            domain_tree = await aggregate_domains_recursive(domain_tree, llm, max_tree_depth=5)
            log.info("aggregate_recursive_done", domains=len(domain_tree))
        except Exception:
            log.warning("aggregate_recursive_failed", exc_info=True)
```

- [ ] **Step 2: Verify no tests break**

Run: `python -m pytest tests/wiki/test_domain_planning_nodes.py tests/wiki/test_domain_compose_node.py -v --timeout=30 2>&1 | tail -20`
Expected: All existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/nodes/classify.py
git commit -m "feat(wiki): integrate aggregate_domains_recursive into decompose pipeline"
```

---

### Task 4: Add `user_edited` marking in DomainManagementService

**Files:**
- Modify: `wiki/domain_management_service.py`
- Modify: `tests/wiki/test_domain_management_service.py`

- [ ] **Step 1: Check existing `user_modified` usage**

The file already sets `"user_modified": True` in `rename_domain` (line 43). Extend this pattern to all mutation methods.

- [ ] **Step 2: Add `user_edited=True` to `move_domain`, `merge_domains`, `create_subdomain`**

In `wiki/domain_management_service.py`:

For `move_domain` — after the existing `move_section` call, add:
```python
        await self._wiki_store.update_section_properties(section_uid, {"user_edited": True})
```

For `merge_domains` — after the merge operation, add:
```python
        await self._wiki_store.update_section_properties(target_uid, {"user_edited": True})
```

For `create_subdomain` — after the section is created, add `user_edited=True` to the parent:
```python
        await self._wiki_store.update_section_properties(parent_uid, {"user_edited": True})
```

- [ ] **Step 3: Run existing tests**

Run: `python -m pytest tests/wiki/test_domain_management_service.py -v --timeout=30 2>&1 | tail -20`
Expected: All tests PASS (or need minor fixture updates for the new property)

- [ ] **Step 4: Commit**

```bash
git add wiki/domain_management_service.py tests/wiki/test_domain_management_service.py
git commit -m "feat(wiki): mark user-edited domains with user_edited property"
```

---

### Task 5: Add manual reorganize API endpoint

**Files:**
- Modify: `api/routes/wiki_domain_routes.py`

- [ ] **Step 1: Add the endpoint**

In `api/routes/wiki_domain_routes.py`, add a new endpoint:

```python
@router.post("/reorganize")
async def reorganize_domains(
    business_id: str = Query(...),
    reset_user_edits: bool = Query(False),
    container: AppContainer = Depends(get_container),
):
    """Manually trigger domain theme aggregation."""
    wiki_store = container.wiki_store
    llm = container.llm

    tree_data = await wiki_store.get_wiki_tree(business_id)
    if not tree_data:
        return {"success": False, "message": "No domain tree found"}

    from wiki.domain_merger import aggregate_domains_recursive

    if reset_user_edits and tree_data:
        for node in tree_data:
            _clear_user_edited(node)

    result = await aggregate_domains_recursive(tree_data, llm, max_tree_depth=5)
    return {"success": True, "domains_before": len(tree_data), "domains_after": len(result)}


def _clear_user_edited(node: dict) -> None:
    node.pop("user_edited", None)
    for child in node.get("children", []):
        _clear_user_edited(child)
```

- [ ] **Step 2: Verify it compiles**

Run: `python -c "from api.routes.wiki_domain_routes import router; print('OK')" 2>&1`
Expected: OK or import chain issues to fix

- [ ] **Step 3: Commit**

```bash
git add api/routes/wiki_domain_routes.py
git commit -m "feat(api): add POST /wiki/domains/reorganize endpoint"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/wiki/test_domain_merger.py tests/wiki/test_domain_theme_aggregation.py -v 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 2: Check for lint errors**

Run: `python -m ruff check wiki/domain_merger.py wiki/nodes/classify.py wiki/dependency_graph.py api/routes/wiki_domain_routes.py 2>&1 | tail -20`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 3: Commit any lint fixes if needed**

```bash
git add -A && git commit -m "fix: lint cleanup for domain aggregation"
```
