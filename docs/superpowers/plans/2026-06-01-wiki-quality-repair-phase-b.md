# Wiki Quality Repair Phase B — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 6 remaining structural wiki quality issues after Phase A (empty/duplicate sections, hierarchy inconsistency, disambiguation titles, thin overviews, DomainAnchor stability, single-module topic invariant) via pipeline code only — then full-regenerate and audit.

**Architecture:** Post-linking graph hygiene (empty section GC + consolidated section writes) + deterministic prefix-family tree enforcement layered on Phase A's DomainReviewAgent + HAC anchor constraints for regeneration stability + aligned content thresholds in config/finalize/quality_gate. No frontend changes in this phase.

**Tech Stack:** Python 3.12, pytest, numpy, sklearn, structlog, FalkorDB (WikiSection/WikiPage graph), GenericAgent framework

**Spec:** `docs/superpowers/specs/wiki-quality-repair-v13.md` §4.2 (Phase B items B1–B3, extended for post-Phase-A audit findings)

**Prerequisite:** Phase A merged and deployed (`docs/superpowers/plans/2026-06-01-wiki-quality-repair-phase-a.md` complete).

---

## Prioritized Task List

| # | Task | Priority | Risk | Est. |
|---|------|----------|------|------|
| **1** | Single-module topic invariant | P2 | Low | 0.5d |
| **2** | Thin overview threshold alignment | P2 | Low | 0.5d |
| **3** | Empty section GC after tree linking | P1 | Medium | 1d |
| **4** | Enhanced slug/display dedup + single section writer | P1 | Medium | 1d |
| **5** | Prefix-family hierarchy enforcement | P1 | Medium | 1.5d |
| **6** | DomainReviewAgent tree-level operations | P1 | Medium | 1d |
| **7** | Strip unnecessary disambiguation title suffixes | P2 | Low | 0.5d |
| **8** | DomainAnchor HAC cannot-link + seed clusters | P2 | Medium | 1.5d |
| **9** | Persist domain module signatures | P2 | Low | 0.5d |

**Out of scope (P3):** Frontend nav title display (`dashboard/src/components/wiki/WikiNavigationLinks.tsx`) — deferred to a separate frontend phase per Python-only constraint.

---

## Dependencies

```
Phase A (placement, compound titles, fences) ──┐
                                               │
Task 1 (single-module topic) ──────────────────┼── independent quick wins
Task 2 (thin overview thresholds) ─────────────┘
         │
         ▼
Task 4 (slug/display dedup) ──► Task 3 (empty section GC)
         │
         ▼
Task 5 (prefix-family grouping) ──► Task 6 (DomainReviewAgent tree ops)
         │
         ▼
Task 7 (strip disambiguation) ── depends on Phase A placement + Task 5/6
         │
Task 8 (anchor HAC) ── depends on Phase A prefix penalty in clusterer
         │
         ▼
Task 9 (domain signatures) ── depends on Task 8 anchor upsert path
         │
         ▼
Full regenerate + audit_wiki_data.py
```

---

## Suggested Implementation Order

1. **Tasks 1 + 2** (parallel) — low risk, immediate audit metric wins
2. **Task 4** then **Task 3** — fix root cause before GC validates cleanup
3. **Tasks 5 + 6** (sequential) — hierarchy fixes need agent tree tools after deterministic pass
4. **Task 7** — after hierarchy/placement stable
5. **Tasks 8 + 9** (sequential) — anchor stability for next regeneration
6. **Full regenerate** on dev + `audit_wiki_data.py --full-content`

---

## Success Criteria (next audit)

| Metric | Phase A target | Phase B target |
|--------|---------------|----------------|
| `empty_sections` (children_count=0, non-root) | 6+ | **0** |
| `duplicate_section_uids` | 2+ | **0** |
| `duplicate_titles` (exact, cross-page) | 2+ | **0** |
| `disambiguation_brackets` `(domain-slug)` suffix | ≤2 | **0** |
| `thin_overview` (<2000 chars) | 1 | **0** |
| `domains_without_topics` | ≤2 | **0** |
| `hierarchy_prefix_mismatch` (same prefix at L1 + nested) | 2+ | **0** |
| `domain_mapping_stability` (vs anchored baseline) | N/A | **<10% slug churn** |
| `shell_sections` (nav containers, no topic children) | 3 | **0** |
| Composite score | 7.5+ | **8.0+** |

**Verification command:**
```bash
uv run python scripts/audit_wiki_data.py --repo ultron --full-content
```

---

## Task 1: Single-Module Topic Invariant

**Priority:** P2 | **Risk:** Low

**Problem:** `plan_topics_min_modules=1` allows planning, but LLM can still return `should_split=False` and mechanical split requires ≥2 modules — single-module leaf domains end up with overview only.

**Files:**
- Modify: `wiki/domain_doc_agent.py` (`plan_topics`, `_build_single_module_topic`)
- Test: `tests/wiki/test_domain_protection_v10.py` (extend) or `tests/wiki/test_single_module_topic_invariant.py` (new)

**Approach:** After `_plan_topics` returns, if `len(module_names) == 1` and no multi-topic outline, synthesize a forced `DomainTopicOutline(should_split=True, topics=[single topic])` using `derive_semantic_title` for the title and `_derive_slug_from_modules` for slug. Skip LLM decline path entirely for single-module domains.

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_single_module_topic_invariant.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent
from wiki.llm_schemas import DomainTopicOutline, OutlineTopicItem


@pytest.mark.asyncio
async def test_single_module_domain_forces_one_topic():
    agent = DomainDocAgent(
        domain_name="family-business-event",
        domain_display_name="家族业务事件",
        page_agent=MagicMock(),
    )
    llm_declined = DomainTopicOutline(
        should_split=False,
        topics=[OutlineTopicItem(title="家族业务事件", modules=["FamilyEventService"], description="")],
    )
    agent._plan_topics = AsyncMock(return_value=llm_declined)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.plan_topics_min_modules = 1
        mock_settings.return_value.wiki.min_overview_len_for_topics = 99999
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.topic_force_split_threshold = 4

        result = await agent.plan_topics(MagicMock(), ["FamilyEventService"])

    assert result is not None
    assert len(result) == 1
    assert result[0].modules == ["FamilyEventService"]
    assert "|" not in result[0].title
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_single_module_topic_invariant.py -v`
Expected: FAIL — `result is None`

- [ ] **Step 3: Implement forced single-topic path**

Add to `wiki/domain_doc_agent.py` inside `plan_topics`, after the mechanical split block and before `return None`:

```python
        if len(module_names) == 1:
            forced = self._build_single_module_topic(module_names[0])
            if forced:
                self._topic_split_done = True
                self._topic_outline = forced
                return forced.topics
```

Add method:

```python
    def _build_single_module_topic(self, module_name: str) -> DomainTopicOutline | None:
        from wiki.content_guards import derive_semantic_title

        title = derive_semantic_title(
            modules=[module_name],
            domain_display_name=self.domain_display_name,
            summaries=getattr(self, "_module_summaries", {}),
            content=None,
        )
        slug = _derive_slug_from_modules([module_name])
        topic = OutlineTopicItem(title=title, modules=[module_name], description="", slug=slug)
        topics = _resolve_topic_slugs([topic], self.domain_name, getattr(self, "_global_topic_slugs", None))
        return DomainTopicOutline(should_split=True, topics=topics)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_single_module_topic_invariant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/domain_doc_agent.py tests/wiki/test_single_module_topic_invariant.py
git commit -m "fix(wiki): force single topic for single-module leaf domains"
```

---

## Task 2: Thin Overview Threshold Alignment

**Priority:** P2 | **Risk:** Low

**Problem:** `domain_agent_early_exit_min_chars=500` lets agents stop early; `finalize.SHELL_DOMAIN_MIN_CHARS=500` rejects only below 500 while `overview_min_content_chars=2000` is checked elsewhere inconsistently. `timestamp-id-list-persistence` (666 chars) slips through.

**Files:**
- Modify: `core/config.py` (`domain_agent_early_exit_min_chars`)
- Modify: `wiki/nodes/finalize.py` (`SHELL_DOMAIN_MIN_CHARS`, use config)
- Modify: `wiki/domain_doc_agent.py` (early-exit check uses config — verify call site)
- Test: `tests/wiki/test_finalize_v10_batch_b.py`, `tests/wiki/test_domain_agent_early_exit.py`

**Approach:** Raise `domain_agent_early_exit_min_chars` default to 1500. Replace hardcoded `SHELL_DOMAIN_MIN_CHARS = 500` with a function reading `overview_min_content_chars` (2000). Ensure quality_gate and finalize use the same threshold for domain_overview (not topic_index).

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/wiki/test_finalize_v10_batch_b.py

def test_shell_domain_min_chars_matches_overview_config():
    from core.config import AppWikiFlags
    from wiki.nodes.finalize import get_shell_domain_min_chars

    flags = AppWikiFlags(overview_min_content_chars=2000)
    assert get_shell_domain_min_chars(flags) == 2000


def test_early_exit_min_chars_default_1500():
    from core.config import AppWikiFlags

    assert AppWikiFlags().domain_agent_early_exit_min_chars == 1500
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/wiki/test_finalize_v10_batch_b.py::test_shell_domain_min_chars_matches_overview_config tests/wiki/test_finalize_v10_batch_b.py::test_early_exit_min_chars_default_1500 -v`

- [ ] **Step 3: Implement**

In `core/config.py`:
```python
domain_agent_early_exit_min_chars: int = Field(default=1500, ge=0)
```

In `wiki/nodes/finalize.py`, replace constant:
```python
def get_shell_domain_min_chars(wiki: Any | None = None) -> int:
    from core.config import get_settings

    cfg = wiki or get_settings().wiki
    return int(getattr(cfg, "overview_min_content_chars", 2000))
```

Update reject check at ~L746 to use `get_shell_domain_min_chars()`.

- [ ] **Step 4: Run affected tests**

Run: `uv run pytest tests/wiki/test_finalize_v10_batch_b.py tests/wiki/test_domain_agent_early_exit.py tests/wiki/nodes/test_finalize_stub_reject.py -v`
Expected: PASS (update `test_shell_domain_min_chars_constant` to use config-driven helper)

- [ ] **Step 5: Commit**

```bash
git add core/config.py wiki/nodes/finalize.py tests/wiki/test_finalize_v10_batch_b.py
git commit -m "fix(wiki): align overview reject threshold to overview_min_content_chars (2000)"
```

---

## Task 3: Empty Section GC After Tree Linking

**Priority:** P1 | **Risk:** Medium

**Problem:** 6+ WikiSection nodes have `children_count=0` (e.g. `family-task-strategy`, `intimacy-relation`) — orphaned shells from collapsed domains, failed links, or stale sections from prior runs.

**Files:**
- Create: `wiki/section_gc.py` (focused GC helper)
- Modify: `wiki/tree_linker.py` (`link_pages_to_nested_tree` — call GC at end)
- Modify: `store/wiki_tree_store.py` (query helper if needed)
- Test: `tests/wiki/test_section_gc.py` (new)

**Approach:** After all HAS_CHILD edges are created in `link_pages_to_nested_tree`, run `prune_empty_domain_sections(business_id)`:
1. Find all `WikiSection` with `section_type=business_domain` under the space (except `__root__`)
2. Delete sections with zero outgoing HAS_CHILD edges (sections + pages)
3. Log pruned UIDs via structlog

Do **not** delete sections that have WikiPage children (overview/topic pages count as children).

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_section_gc.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_prune_empty_sections_deletes_leaf_without_children():
    from wiki.section_gc import prune_empty_domain_sections

    store = AsyncMock()
    store.execute_query = AsyncMock(
        side_effect=[
            MagicMock(data=[{"uid": "sec-empty", "title": "家族任务策略"}]),
            MagicMock(data=[{"deleted": 1}]),
        ]
    )
    deleted = await prune_empty_domain_sections(store, business_id="ultron", space_uid="WikiSpace:ultron")
    assert deleted == 1


@pytest.mark.asyncio
async def test_prune_skips_root_section():
    from wiki.section_gc import prune_empty_domain_sections

    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    deleted = await prune_empty_domain_sections(store, business_id="ultron", space_uid="WikiSpace:ultron")
    assert deleted == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/wiki/test_section_gc.py -v`

- [ ] **Step 3: Implement `wiki/section_gc.py`**

```python
"""Garbage-collect empty WikiSection nodes after tree linking."""
from __future__ import annotations

from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_FIND_EMPTY_Q = (
    "MATCH (ws {uid: $space_uid})-[:HAS_CHILD* {view_type: 'business_domain'}]->(s:WikiSection) "
    "WHERE NOT s.title = '__root__' "
    "AND NOT (s)-[:HAS_CHILD {view_type: 'business_domain'}]->() "
    "RETURN s.uid AS uid, s.title AS title"
)

_DELETE_Q = (
    "UNWIND $uids AS uid "
    "MATCH (s:WikiSection {uid: uid}) "
    "DETACH DELETE s "
    "RETURN count(s) AS deleted"
)


async def prune_empty_domain_sections(
    wiki_store: Any,
    *,
    business_id: str,
    space_uid: str,
) -> int:
    find_result = await wiki_store.execute_query(_FIND_EMPTY_Q, {"space_uid": space_uid})
    rows = getattr(find_result, "data", None) or []
    uids = [str(r["uid"]) for r in rows if r.get("uid")]
    if not uids:
        return 0
    del_result = await wiki_store.execute_query(_DELETE_Q, {"uids": uids})
    del_rows = getattr(del_result, "data", None) or []
    deleted = int(del_rows[0].get("deleted", 0)) if del_rows else 0
    log.info("empty_sections_pruned", business_id=business_id, deleted=deleted, uids=uids)
    return deleted
```

Wire into `tree_linker.py` at end of `link_pages_to_nested_tree`:
```python
        from wiki.section_gc import prune_empty_domain_sections
        from wiki.tree_builder import WikiTreeBuilder

        await prune_empty_domain_sections(
            self._wiki_store,
            business_id=business_id,
            space_uid=tree_builder.generate_space_uid(business_id),
        )
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/wiki/test_section_gc.py -v`

- [ ] **Step 5: Commit**

```bash
git add wiki/section_gc.py wiki/tree_linker.py tests/wiki/test_section_gc.py
git commit -m "fix(wiki): GC empty WikiSection nodes after tree linking"
```

---

## Task 4: Enhanced Slug Dedup + Single Section Writer

**Priority:** P1 | **Risk:** Medium

**Problem:** Dual section writers (`persist_classification` early + `tree_linker` late) create/update the same UIDs but stale sections survive; near-duplicate slug dedup misses same `display_name` under different paths (duplicate UIDs for 关系管理, 用户权益).

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py` (`_dedup_sub_domains`, `_dedup_parallel_naming_results`)
- Modify: `wiki/tree_linker.py` (skip redundant root creation when sections exist)
- Modify: `wiki/nodes/persist_classification.py` (document/idempotent contract — no duplicate create logic)
- Test: `tests/wiki/test_slug_dedup_v11.py`, `tests/wiki/nodes/test_dedup_decompose.py`, new `tests/wiki/test_section_writer_idempotent.py`

**Approach:**

1. **Display-name dedup in tree:** Extend `_dedup_sub_domains` to merge sibling nodes with identical `display_name` (keep the one with more modules), re-slug with numeric suffix if needed.

2. **Semantic suffix guard:** In `_dedup_parallel_naming_results`, before `new_slug = f"{slug}-{suffix}"`, skip suffix if `suffix` is already a segment of `slug` (prevents `closed-friend-closed-friend` — partially fixed, verify edge cases).

3. **Single writer contract:** Add flag `sections_persisted: bool` to pipeline state. In `tree_linker._ensure_root()`, skip upsert if state indicates sections already persisted (pass via `reassembly_succeeded` or new kwarg). `persist_classification` remains the authoritative early writer; `tree_linker` only creates **missing** sections and links pages — never duplicates display names.

- [ ] **Step 1: Write failing test for display-name merge**

```python
# Append to tests/wiki/nodes/test_dedup_decompose.py

def test_dedup_sub_domains_merges_same_display_name():
    from wiki.nodes.graph_domain_decompose import _dedup_sub_domains

    subs = [
        {"slug": "relation-mgmt-a", "display_name": "关系管理", "modules": [("r", "SvcA")]},
        {"slug": "relation-mgmt-b", "display_name": "关系管理", "modules": [("r", "SvcB")]},
    ]
    result = _dedup_sub_domains(subs, parent_display_name="关系")
    assert len(result) == 1
    assert len(result[0]["modules"]) == 2
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/wiki/nodes/test_dedup_decompose.py::test_dedup_sub_domains_merges_same_display_name -v`

- [ ] **Step 3: Implement display-name merge in `_dedup_sub_domains`**

```python
    by_display: dict[str, dict] = {}
    for sub in named_subs:
        display = sub.get("display_name", "").strip()
        if display and display in by_display:
            by_display[display]["modules"] = list(by_display[display].get("modules", [])) + list(sub.get("modules", []))
            children = sub.get("children") or []
            if children:
                by_display[display].setdefault("children", []).extend(children)
            continue
        if display:
            by_display[display] = sub
        else:
            by_display[sub.get("slug", f"unnamed-{len(by_display)}")] = sub
    named_subs = list(by_display.values())
```

(Integrate with existing ancestor-collision logic — read full function before editing.)

- [ ] **Step 4: Add tree_linker idempotent guard**

In `tree_linker.link_pages_to_nested_tree`, add parameter `sections_already_persisted: bool = False`. When True, skip `_ensure_root()` body except edge repair. Pass from `business_pipeline_runner.py` using `pipeline_result.classification_persisted`.

- [ ] **Step 5: Run dedup + decompose tests**

Run: `uv run pytest tests/wiki/nodes/test_dedup_decompose.py tests/wiki/test_slug_dedup_v11.py tests/wiki/nodes/test_graph_domain_decompose.py -v --timeout=120`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/graph_domain_decompose.py wiki/tree_linker.py wiki/business_pipeline_runner.py tests/
git commit -m "fix(wiki): merge duplicate display-name sub-domains and idempotent section writes"
```

---

## Task 5: Prefix-Family Hierarchy Enforcement

**Priority:** P1 | **Risk:** Medium

**Problem:** `intimacy-task-execution` sits at L1 while `intimacy-relationship` nests under `关系` — same business prefix split across hierarchy paths because `_aggregate_siblings_by_theme` is LLM-driven and non-deterministic.

**Files:**
- Create: `wiki/prefix_family_grouper.py`
- Modify: `wiki/nodes/graph_domain_decompose.py` (call after Step 8.5 theme aggregation)
- Test: `tests/wiki/test_prefix_family_grouper.py` (new)

**Approach:** Deterministic post-aggregation pass using `_extract_business_prefix` from `domain_semantic_clusterer`:
1. Collect all L1 domain nodes and their prefixes
2. If ≥2 L1 nodes share prefix `P` and none is a theme parent for the others, create/wrap under synthetic parent `{P}-family` (display: localized label from prefix)
3. If an L1 node has prefix `P` but a nested child under a different branch also has prefix `P`, reparent the L1 node under the existing `{P}` theme parent
4. Respect `user_modified` nodes — skip them

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_prefix_family_grouper.py
from wiki.prefix_family_grouper import enforce_prefix_family_grouping


def test_groups_same_prefix_l1_domains_under_parent():
    tree = [
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m1"], "children": []},
        {"name": "intimacy-online", "display_name": "亲密度在线", "modules": ["m2"], "children": []},
        {"name": "family-core", "display_name": "家族核心", "modules": [], "children": [
            {"name": "family-chest", "display_name": "家族宝箱", "modules": ["m3"], "children": []},
        ]},
    ]
    result = enforce_prefix_family_grouping(tree)
    intimacy_parents = [n for n in result if n["name"] == "intimacy-family" or "intimacy" in n["name"]]
    assert any(n.get("children") and len(n["children"]) >= 2 for n in intimacy_parents)


def test_does_not_move_user_modified_nodes():
    tree = [
        {"name": "intimacy-a", "display_name": "A", "modules": ["m1"], "children": [], "user_modified": True},
        {"name": "intimacy-b", "display_name": "B", "modules": ["m2"], "children": []},
    ]
    result = enforce_prefix_family_grouping(tree)
    assert len(result) == 2  # unchanged
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/wiki/test_prefix_family_grouper.py -v`

- [ ] **Step 3: Implement `wiki/prefix_family_grouper.py`**

Use `_extract_business_prefix(node["name"], None)` for each node. Group L1 siblings by prefix; when len(group) >= 2, wrap in parent node. Return modified tree.

- [ ] **Step 4: Wire into `graph_domain_decompose.py` after theme aggregation**

```python
    if domain_tree:
        from wiki.prefix_family_grouper import enforce_prefix_family_grouping

        domain_tree = enforce_prefix_family_grouping(domain_tree)
        log.info("prefix_family_grouping_applied", l1_count=len(domain_tree))
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `uv run pytest tests/wiki/test_prefix_family_grouper.py tests/wiki/test_theme_aggregation_f10.py -v`

- [ ] **Step 6: Commit**

```bash
git add wiki/prefix_family_grouper.py wiki/nodes/graph_domain_decompose.py tests/wiki/test_prefix_family_grouper.py
git commit -m "fix(wiki): enforce prefix-family grouping after theme aggregation"
```

---

## Task 6: DomainReviewAgent Tree-Level Operations

**Priority:** P1 | **Risk:** Medium

**Problem:** Phase A's DomainReviewAgent handles flat `domain_mapping` moves but not tree reparenting — hierarchy mismatches need `propose_reparent_domain(child_slug, new_parent_slug, reason)`.

**Files:**
- Modify: `wiki/agents/domain_review_agent.py`
- Modify: `wiki/nodes/graph_domain_decompose.py` (Step 5.6 — tree review after prefix grouping)
- Test: `tests/wiki/agents/test_domain_review_agent.py` (extend)

**Approach:** Add tree state (`domain_tree: list[dict]`) to agent. New tools:
- `inspect_tree()` — return L1/L2 structure
- `propose_reparent_domain(child_slug, new_parent_slug | None, reason)` — move node to new parent or promote to L1
- `validate_prefix_consistency()` — reuse prefix grouper diff output

On `apply_decisions()`, apply tree moves then flatten back to update `domain_mapping` if needed. Fallback: if LLM fails, apply Task 5 deterministic grouping only.

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/wiki/agents/test_domain_review_agent.py

def test_propose_reparent_domain_moves_child():
    from wiki.agents.domain_review_agent import DomainReviewAgent

    tree = [
        {"name": "relations", "display_name": "关系", "modules": [], "children": [
            {"name": "intimacy-core", "display_name": "亲密度", "modules": ["m1"], "children": []},
        ]},
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m2"], "children": []},
    ]
    agent = DomainReviewAgent(llm=MagicMock())
    agent.set_tree_data(tree, {}, {})

    result = agent._propose_reparent_domain("intimacy-task-execution", "relations", "prefix family")
    assert result["status"] == "accepted"
    updated = agent.apply_tree_decisions()
    child_names = [c["name"] for c in updated[0]["children"]]
    assert "intimacy-task-execution" in child_names
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/wiki/agents/test_domain_review_agent.py::test_propose_reparent_domain_moves_child -v`

- [ ] **Step 3: Implement tree methods in `domain_review_agent.py`**

Add `set_tree_data`, `pending_tree_reparents`, `_propose_reparent_domain`, `apply_tree_decisions`. Tree reparent removes child from old parent (or L1 list) and appends to new parent's `children`.

- [ ] **Step 4: Wire into decompose node**

After Task 5 grouping, if `wiki_cfg.enable_domain_review_agent`:
```python
    reviewer.set_tree_data(domain_tree, domain_display_names, module_summaries)
    domain_tree = reviewer.apply_tree_decisions() or domain_tree
```

- [ ] **Step 5: Run agent tests**

Run: `uv run pytest tests/wiki/agents/test_domain_review_agent.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/agents/domain_review_agent.py wiki/nodes/graph_domain_decompose.py tests/wiki/agents/test_domain_review_agent.py
git commit -m "feat(wiki): add DomainReviewAgent tree reparent operations"
```

---

## Task 7: Strip Unnecessary Disambiguation Title Suffixes

**Priority:** P2 | **Risk:** Low

**Problem:** 5 pages with `(domain-slug)` suffix — `_deduplicate_exact_titles` adds domain slug when titles collide; after Phase A placement fixes, collisions should be rare and suffixes should be stripped.

**Files:**
- Modify: `wiki/nodes/finalize.py` (`_strip_disambiguation_suffixes`, call before publish)
- Modify: `wiki/content_guards.py` (optional `is_disambiguation_title`, `strip_disambiguation_suffix`)
- Test: `tests/wiki/nodes/test_finalize_disambiguation.py` (new)

**Approach:** After `_deduplicate_titles`, run cleanup pass:
1. Detect titles matching `^(.+)（([a-z0-9-]+)）$` (full-width parens from `_title_with_suffix`)
2. If base title is unique among all pages after stripping, remove suffix
3. If two pages still collide after strip, keep suffix on both

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/nodes/test_finalize_disambiguation.py
from wiki.nodes.finalize import _strip_disambiguation_suffixes


def test_strips_suffix_when_base_title_unique():
    pages = [
        {"title": "关系管理（user-wealth-charm-level）", "path": "/__domains__/relation-mgmt/_topic/t1", "business_domain": "relation-mgmt"},
        {"title": "家族核心运营", "path": "/__domains__/family/_overview", "page_type": "domain_overview"},
    ]
    result = _strip_disambiguation_suffixes(pages)
    assert result[0]["title"] == "关系管理"


def test_keeps_suffix_when_still_duplicate():
    pages = [
        {"title": "用户权益（domain-a）", "business_domain": "domain-a", "path": "p1"},
        {"title": "用户权益（domain-b）", "business_domain": "domain-b", "path": "p2"},
    ]
    result = _strip_disambiguation_suffixes(pages)
    assert result[0]["title"] != "用户权益" or result[1]["title"] != "用户权益"
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/wiki/nodes/test_finalize_disambiguation.py -v`

- [ ] **Step 3: Implement in `finalize.py`**

```python
_DISAMBIG_SUFFIX_RE = re.compile(r"^(.+?)（([a-z0-9][a-z0-9-]*)）$")


def _strip_disambiguation_suffixes(pages: list[dict]) -> list[dict]:
    result = [dict(p) for p in pages]
    bases: dict[str, list[int]] = {}
    for i, page in enumerate(result):
        m = _DISAMBIG_SUFFIX_RE.match(str(page.get("title", "")))
        if m:
            bases.setdefault(m.group(1), []).append(i)
    for base, indices in bases.items():
        if len(indices) != 1:
            continue
        idx = indices[0]
        result[idx] = {**result[idx], "title": base}
    return result
```

Call in `_deduplicate_titles` after exact dedup:
```python
    result = _deduplicate_exact_titles(result)
    result = _strip_disambiguation_suffixes(result)
    return _ensure_title_uniqueness(result)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/wiki/nodes/test_finalize_disambiguation.py -v`

- [ ] **Step 5: Commit**

```bash
git add wiki/nodes/finalize.py tests/wiki/nodes/test_finalize_disambiguation.py
git commit -m "fix(wiki): strip unnecessary domain-slug disambiguation title suffixes"
```

---

## Task 8: DomainAnchor HAC Cannot-Link + Seed Clusters

**Priority:** P2 | **Risk:** Medium

**Problem:** DomainAnchor loads pinned modules but HAC ignores them — re-clustering drifts business lines. Spec B1: pinned modules cannot link to modules in different anchor domains; anchor domains seed initial clusters.

**Files:**
- Modify: `wiki/domain_semantic_clusterer.py` (`_apply_anchor_constraints`, `cluster` signature)
- Modify: `wiki/nodes/graph_domain_decompose.py` (`_embedding_clustering` — pass `pinned_module_domains`)
- Test: `tests/wiki/test_domain_semantic_clusterer.py`, `tests/wiki/test_domain_anchor_v11.py`

**Approach:**
1. Accept `pinned_domains: dict[tuple[str,str], str]` mapping module pair → domain slug
2. In distance matrix: if module A pinned to domain X and module B pinned to domain Y (X≠Y), set `dist[i,j] = dist[j,i] = 2.0` (cannot-link)
3. Seed clusters: pre-group pinned modules by domain slug before HAC; run HAC only within unassigned modules + merge seeded groups
4. Config flag: `AppWikiFlags.enable_anchor_cluster_constraints: bool = True`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/wiki/test_domain_semantic_clusterer.py

class TestAnchorConstraints:
    def test_different_anchor_domains_cannot_link(self):
        import numpy as np
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        dist = np.array([[0.0, 0.3], [0.3, 0.0]])
        modules = [("repo", "ModA"), ("repo", "ModB")]
        pinned = {("repo", "ModA"): "domain-x", ("repo", "ModB"): "domain-y"}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_anchor_constraints(dist.copy(), modules, pinned)
        assert result[0, 1] == pytest.approx(2.0)

    def test_same_anchor_domain_unchanged(self):
        import numpy as np
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        dist = np.array([[0.0, 0.3], [0.3, 0.0]])
        modules = [("repo", "ModA"), ("repo", "ModB")]
        pinned = {("repo", "ModA"): "domain-x", ("repo", "ModB"): "domain-x"}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_anchor_constraints(dist.copy(), modules, pinned)
        assert result[0, 1] == pytest.approx(0.3, abs=1e-6)
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py::TestAnchorConstraints -v`

- [ ] **Step 3: Implement `_apply_anchor_constraints` and wire into `_compute_distance_matrix`**

- [ ] **Step 4: Pass pinned map from decompose**

In `_embedding_clustering`, build `pinned_domains` from `state["pinned_modules"]` and pass to `clusterer.cluster(..., pinned_domains=pinned_domains)`.

- [ ] **Step 5: Run clusterer + anchor tests**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py tests/wiki/test_domain_anchor_v11.py -v --timeout=120`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/domain_semantic_clusterer.py wiki/nodes/graph_domain_decompose.py core/config.py tests/
git commit -m "feat(wiki): apply DomainAnchor cannot-link constraints in HAC clustering"
```

---

## Task 9: Persist Domain Module Signatures

**Priority:** P2 | **Risk:** Low

**Problem:** Need stable domain assignments across regeneration — pin known-good domains by persisting a hash of sorted module keys per domain.

**Files:**
- Modify: `wiki/persistence.py` (`upsert_domain_anchor` — add `module_signature` property)
- Modify: `wiki/nodes/persist_classification.py` (compute signature on save)
- Test: `tests/wiki/test_domain_anchor_signatures.py` (new)

**Approach:** Signature = SHA256 of sorted `f"{repo}|{name}"` keys joined by `\n`. Store on `DomainAnchor.module_signature`. Quality gate or decompose can compare post-cluster signature drift and log warning when >10% modules differ for anchored slugs.

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_domain_anchor_signatures.py
from wiki.persistence import compute_domain_module_signature


def test_signature_stable_for_same_modules():
    mods = [("repo", "B"), ("repo", "A")]
    assert compute_domain_module_signature(mods) == compute_domain_module_signature(list(reversed(mods)))


def test_signature_changes_when_modules_differ():
    a = compute_domain_module_signature([("r", "A")])
    b = compute_domain_module_signature([("r", "A"), ("r", "B")])
    assert a != b
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/wiki/test_domain_anchor_signatures.py -v`

- [ ] **Step 3: Implement**

```python
# wiki/persistence.py (module-level helper)
import hashlib

def compute_domain_module_signature(modules: list[tuple[str, str]]) -> str:
    keys = sorted(f"{repo}|{name}" for repo, name in modules)
    payload = "\n".join(keys).encode()
    return hashlib.sha256(payload).hexdigest()
```

Update `upsert_domain_anchor` Cypher to `SET d.module_signature = $sig`. Call from `save_domain_classification`.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/wiki/test_domain_anchor_signatures.py -v`

- [ ] **Step 5: Commit**

```bash
git add wiki/persistence.py wiki/nodes/persist_classification.py tests/wiki/test_domain_anchor_signatures.py
git commit -m "feat(wiki): persist domain module signatures on DomainAnchor nodes"
```

---

## Final Verification

- [ ] **Run full wiki test suite**

```bash
uv run pytest tests/wiki/ -x --timeout=120
```

- [ ] **Regenerate wiki on dev**

```bash
ssh dev "cd ~/review-bot/knowledge-base-service && \
  PYTHONPATH=. .venv/bin/python -m wiki.cli regenerate --repo ultron --full-rebuild"
```

- [ ] **Run audit and compare metrics**

```bash
ssh dev "cd ~/review-bot/knowledge-base-service && \
  PYTHONPATH=. .venv/bin/python scripts/audit_wiki_data.py --repo ultron --full-content"
```

- [ ] **Update audit doc** — record V28 metrics in `docs/wiki-quality-audit.md`

---

## Self-Review Checklist

**Spec coverage:**
- [x] B1 DomainAnchor HAC → Task 8
- [x] B2 Shell section navigation → Tasks 3 + 4 (GC + dedup; shell overview content deferred — tree_linker already synthesizes child cards)
- [ ] B3 Frontend nav → Out of scope (Python-only)
- [x] P1 empty/duplicate sections → Tasks 3 + 4
- [x] P1 hierarchy inconsistency → Tasks 5 + 6
- [x] P2 disambiguation titles → Task 7
- [x] P2 thin overview → Task 2
- [x] P2 DomainAnchor signatures → Task 9
- [x] P2 single-module topic → Task 1

**Placeholder scan:** No TBD/TODO in task steps.

**Type consistency:** `enforce_prefix_family_grouping`, `_strip_disambiguation_suffixes`, `prune_empty_domain_sections`, `compute_domain_module_signature` names used consistently across tasks.

**Risk summary:**

| Task | Risk | Mitigation |
|------|------|------------|
| 1 | Low-quality single topic | `derive_semantic_title` + topic_min_content_chars gate |
| 2 | More overview rejects | Regeneration replaces rejected; tree_linker synthesizes fallback |
| 3 | Accidental section delete | Only delete sections with zero HAS_CHILD edges |
| 4 | Over-merge display names | Merge only exact display_name match among siblings |
| 5 | Over-grouping prefixes | Skip `user_modified`; require ≥2 same-prefix L1 nodes |
| 6 | Agent over-reparent | Reuse move limit; fallback to Task 5 deterministic |
| 7 | Title collision regression | `_ensure_title_uniqueness` safety pass after strip |
| 8 | Anchor rigidity | Flag-gated; only pinned modules get cannot-link |
| 9 | Signature false alarms | Log-only drift warning in Phase B; block in future phase |
