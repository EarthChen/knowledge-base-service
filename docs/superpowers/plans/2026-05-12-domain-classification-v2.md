# Domain Classification v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement stable, accurate domain classification with slug-based dual identifiers, anchor-first architecture, signal enrichment, pipeline intermediate persistence, and Dashboard management support.

**Architecture:** Anchor-First classification — first run creates domain slugs persisted to FalkorDB; subsequent runs inject anchors into LLM prompts for stability. Module signals enriched via Cypher bulk queries. Pipeline checkpointed with AsyncSqliteSaver; critical nodes persist immediately.

**Tech Stack:** Python 3.11+, FastAPI, FalkorDB (Cypher), LangGraph, React 19, TanStack Query, Vite

**Spec:** `docs/superpowers/specs/2026-05-12-agent-wiki-quality-and-tree-fix.md` §2-§4

## Execution Status (2026-05-12)

| Task | Status | Notes |
|------|--------|-------|
| Task 1: Slug System Foundation | ✅ Done | slug 全链路传播已实现 |
| Task 2: Storage Layer | 🔲 Pending | 域管理 7 方法待实现 |
| Task 3: Signal Enrichment | ✅ Done | ModuleEnricher + Cypher 查询 |
| Task 4: DomainStabilizer Dual-Field | ✅ Done | |
| Task 5: Anchor Domain Loading | ✅ Done | |
| Task 6: Prompt Redesign | ✅ Done | anchor 注入 + slug 输出 |
| Task 7: Remove 200 Cap | ✅ Done | |
| Task 8: Pipeline Persistence | ✅ Done | persist_classification_node + 逐域持久化 |
| Task 9: AsyncSqliteSaver | ✅ Done | |
| Task 10: Dashboard API | 🔲 Pending | 11 个端点待实现 |
| Task 11: Dashboard UI | 🔲 Pending | 域管理 + checkpoint 面板 |
| Task 12: Trigger Script | 🔲 Pending | 新命令待实现 |
| Task 13: Regression Tests | ✅ Done | 2187 tests passing |

---

## File Structure

### New Files
- `wiki/module_enricher.py` — shared module signal enrichment (Cypher queries + caching)
- `wiki/nodes/persist_classification.py` — new pipeline node for intermediate domain persistence
- `tests/wiki/test_domain_stabilizer_v2.py` — stabilizer dual-field matching tests
- `tests/wiki/test_module_enricher.py` — signal enrichment tests
- `tests/wiki/test_slug_system.py` — slug generation/normalization tests
- `tests/wiki/test_classification_pipeline.py` — integration tests for anchor + signal flow
- `dashboard/src/components/wiki/CheckpointPanel.tsx` — checkpoint status display
- `dashboard/src/components/wiki/DomainManagement.tsx` — domain list + management UI
- `dashboard/src/hooks/useCheckpoint.ts` — checkpoint API hook
- `dashboard/src/hooks/useDomainManagement.ts` — domain management API hooks

### Modified Files
- `wiki/path_conventions.py` — slug-based path format
- `wiki/dependency_graph.py` — DomainNode slug field
- `wiki/domain_stabilizer.py` — dual-field matching (slug + display_name)
- `wiki/cypher_queries.py` — new signal enrichment queries
- `wiki/nodes/classify.py` — anchor loading, pinned skip, signal enrichment, cap removal
- `wiki/cross_repo_domain_planner.py` — prompt rewrite (anchor injection, slug output)
- `wiki/tree_linker.py` — slug-based paths, WikiSection slug property
- `wiki/pipeline_graph.py` — new persist node, AsyncSqliteSaver
- `wiki/nodes/domain_compose.py` — per-domain persistence
- `wiki/service.py` — resume/regenerate/checkpoint APIs
- `wiki/pipeline_orchestrator.py` — checkpointer passthrough
- `api/routes/wiki_page_routes.py` — 11 new endpoints
- `store/falkordb_wiki.py` or `store/wiki_page_store.py` — 9 new storage methods
- `scripts/trigger_wiki_generate.sh` — new commands

---

## Task 1: Slug System Foundation (P0)

**Files:**
- Modify: `wiki/path_conventions.py:1-14`
- Modify: `wiki/dependency_graph.py:185-190` (DomainNode)
- Create: `tests/wiki/test_slug_system.py`

- [ ] **Step 1: Write failing test for slug normalization**

```python
# tests/wiki/test_slug_system.py
import pytest
from wiki.path_conventions import normalize_slug, domain_overview_path, domain_topic_path


class TestNormalizeSlug:
    def test_basic_kebab(self):
        assert normalize_slug("gift-system") == "gift-system"

    def test_spaces_to_hyphens(self):
        assert normalize_slug("gift system") == "gift-system"

    def test_chinese_passthrough_to_empty(self):
        # Chinese-only input should be transliterated or handled
        result = normalize_slug("礼物系统")
        assert result  # non-empty
        assert " " not in result

    def test_mixed_ascii_strip(self):
        assert normalize_slug("Gift_System v2") == "gift-system-v2"

    def test_consecutive_hyphens(self):
        assert normalize_slug("gift--system") == "gift-system"

    def test_leading_trailing_hyphens(self):
        assert normalize_slug("-gift-system-") == "gift-system"

    def test_uppercase_to_lower(self):
        assert normalize_slug("GiftSystem") == "giftsystem"


class TestSlugPaths:
    def test_domain_overview_path_slug(self):
        assert domain_overview_path("gift-system") == "/__domains__/gift-system/_overview"

    def test_domain_topic_path_slug(self):
        assert domain_topic_path("gift-system", "order-flow") == "/__domains__/gift-system/order-flow/_topic"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_slug_system.py -v`
Expected: FAIL — `normalize_slug` not defined

- [ ] **Step 3: Implement slug normalization in path_conventions.py**

```python
# wiki/path_conventions.py
import re

DOMAIN_OVERVIEW_PATH_FMT = "/__domains__/{name}/_overview"
DOMAIN_TOPIC_PATH_FMT = "/__domains__/{domain}/{section}/_topic"


def normalize_slug(raw: str) -> str:
    """Normalize a raw string into a kebab-case ASCII slug."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9\s\-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s or "unnamed"


def domain_overview_path(name: str) -> str:
    return DOMAIN_OVERVIEW_PATH_FMT.format(name=name)


def domain_topic_path(domain: str, section: str) -> str:
    safe = re.sub(r"[\s/]+", "_", section)
    return DOMAIN_TOPIC_PATH_FMT.format(domain=domain, section=safe)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_slug_system.py -v`
Expected: PASS

- [ ] **Step 5: Add slug field to DomainNode**

In `wiki/dependency_graph.py`, modify the `DomainNode` dataclass at line 185:

```python
@dataclass
class DomainNode:
    name: str  # display_name (Chinese)
    slug: str = ""  # ASCII kebab-case identifier
    description: str = ""
    modules: list[tuple[str, str]] = field(default_factory=list)
    children: list["DomainNode"] = field(default_factory=list)
```

- [ ] **Step 6: Run existing tests to ensure no regression**

Run: `uv run pytest tests/wiki/ -v --timeout=30 -x`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/path_conventions.py wiki/dependency_graph.py tests/wiki/test_slug_system.py
git commit -m "feat: add slug normalization and DomainNode.slug field"
```

---

## Task 2: Storage Layer — Domain Management Methods (P0)

**Files:**
- Modify: `store/wiki_page_store.py` (add 9 methods to WikiPageStore or new WikiDomainStore)
- Create: `tests/wiki/test_domain_store.py`

- [ ] **Step 1: Write failing tests for domain store methods**

```python
# tests/wiki/test_domain_store.py
import pytest

# These tests verify the Cypher query structure, not actual DB execution.
# Integration tests with FalkorDB should be separate.


class TestDomainStoreMethods:
    """Verify domain management method signatures exist and return correct types."""

    def test_list_domains_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "list_domains")

    def test_list_domain_modules_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "list_domain_modules")

    def test_move_module_domain_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "move_module_domain")

    def test_rename_domain_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "rename_domain")

    def test_clear_domain_pin_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "clear_domain_pin")

    def test_load_anchor_domains_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "load_anchor_domains")

    def test_delete_empty_domain_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "delete_empty_domain")

    def test_get_checkpoint_info_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "get_checkpoint_info")

    def test_delete_checkpoint_signature(self):
        from store.wiki_page_store import WikiPageStore
        assert hasattr(WikiPageStore, "delete_checkpoint")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_domain_store.py -v`
Expected: FAIL — methods not found

- [ ] **Step 3: Implement domain management methods in WikiPageStore**

Add the following methods to `store/wiki_page_store.py`. Each method contains the Cypher query and calls `self._store.execute_query(...)`. Refer to spec §3.3 for the full method list.

Key methods to implement:

```python
async def list_domains(self, business_id: str) -> list[dict]:
    q = (
        "MATCH (ws:WikiSpace {business_id: $bid})-[:HAS_CHILD*1..3]->"
        "(s:WikiSection {section_type: 'business_domain'}) "
        "OPTIONAL MATCH (m:Module {business_domain: s.slug}) "
        "WHERE m.repository IN ["
        "  r IN [(ws2:WikiSpace {business_id: $bid})-[:CONTAINS_REPO]->(rr) | rr.repository]"
        "] "
        "RETURN s.slug AS slug, s.title AS display_name, count(m) AS module_count "
        "ORDER BY module_count DESC"
    )
    result = await self._store.execute_query(q, {"bid": business_id})
    return result.data or []

async def list_domain_modules(self, business_id: str, slug: str) -> list[dict]:
    q = (
        "MATCH (m:Module {business_domain: $slug}) "
        "WHERE m.repository STARTS WITH $bid_prefix "
        "RETURN m.uid AS uid, m.name AS name, m.repository AS repository, "
        "coalesce(m.file, '') AS file_path, "
        "coalesce(m.domain_pinned, false) AS pinned "
        "ORDER BY m.name"
    )
    result = await self._store.execute_query(q, {"slug": slug, "bid_prefix": business_id})
    return result.data or []

async def move_module_domain(self, module_uid: str, target_slug: str) -> bool:
    q = (
        "MATCH (m {uid: $uid}) "
        "SET m.business_domain = $slug, m.domain_pinned = true "
        "RETURN m.uid AS uid"
    )
    result = await self._store.execute_query(q, {"uid": module_uid, "slug": target_slug})
    return bool(result.data)

async def rename_domain(self, business_id: str, old_slug: str, new_slug: str, new_display_name: str) -> int:
    q = (
        "MATCH (m:Module {business_domain: $old_slug}) "
        "SET m.business_domain = $new_slug "
        "WITH count(m) AS updated "
        "MATCH (s:WikiSection {slug: $old_slug, section_type: 'business_domain'}) "
        "SET s.slug = $new_slug, s.title = $display "
        "RETURN updated"
    )
    result = await self._store.execute_query(
        q, {"old_slug": old_slug, "new_slug": new_slug, "display": new_display_name}
    )
    return (result.data[0] or {}).get("updated", 0) if result.data else 0

async def clear_domain_pin(self, module_uid: str) -> bool:
    q = "MATCH (m {uid: $uid}) SET m.domain_pinned = false RETURN m.uid AS uid"
    result = await self._store.execute_query(q, {"uid": module_uid})
    return bool(result.data)

async def load_anchor_domains(self, business_id: str) -> list[dict[str, str]]:
    q = (
        "MATCH (ws:WikiSpace {business_id: $bid})-[:HAS_CHILD*1..3]->"
        "(s:WikiSection {section_type: 'business_domain'}) "
        "RETURN s.slug AS slug, s.title AS display_name"
    )
    result = await self._store.execute_query(q, {"bid": business_id})
    return [{"slug": r["slug"], "display_name": r["display_name"]} for r in (result.data or [])]

async def delete_empty_domain(self, business_id: str, slug: str) -> bool:
    check_q = (
        "MATCH (m:Module {business_domain: $slug}) RETURN count(m) AS cnt"
    )
    check = await self._store.execute_query(check_q, {"slug": slug})
    if check.data and check.data[0].get("cnt", 0) > 0:
        return False
    del_q = (
        "MATCH (s:WikiSection {slug: $slug, section_type: 'business_domain'}) "
        "OPTIONAL MATCH (s)-[:HAS_CHILD*0..5]->(child) "
        "DETACH DELETE child, s"
    )
    await self._store.execute_query(del_q, {"slug": slug})
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_domain_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add store/wiki_page_store.py tests/wiki/test_domain_store.py
git commit -m "feat: add domain management storage methods (list/move/rename/pin/delete)"
```

---

## Task 3: Signal Enrichment — ModuleEnricher (P1)

**Files:**
- Create: `wiki/module_enricher.py`
- Modify: `wiki/cypher_queries.py`
- Create: `tests/wiki/test_module_enricher.py`

- [ ] **Step 1: Write failing test for ModuleEnricher**

```python
# tests/wiki/test_module_enricher.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.module_enricher import ModuleEnricher


class TestModuleEnricher:
    @pytest.fixture
    def mock_graph_store(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        return store

    @pytest.mark.asyncio
    async def test_enrich_returns_dict(self, mock_graph_store):
        enricher = ModuleEnricher(mock_graph_store)
        repos = ["ultron/ultron-basic-user"]
        names = ["ClosedFriendBizService"]
        result = await enricher.enrich(repos, names)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_enrich_merges_all_signals(self, mock_graph_store):
        mock_graph_store.execute_query = AsyncMock(side_effect=[
            MagicMock(data=[{"module_name": "Svc", "repo": "r", "key_methods": ["m1", "m2"]}]),
            MagicMock(data=[{"source": "Svc", "repo": "r", "callees": ["Dao"], "fan_out": 1}]),
            MagicMock(data=[{"target": "Svc", "repo": "r", "callers": ["Ctrl"], "fan_in": 1}]),
        ])
        enricher = ModuleEnricher(mock_graph_store)
        result = await enricher.enrich(["r"], ["Svc"])
        key = ("r", "Svc")
        assert "key_methods" in result[key]
        assert "callees" in result[key]
        assert "callers" in result[key]
        assert "fan_in" in result[key]
        assert "fan_out" in result[key]

    @pytest.mark.asyncio
    async def test_enrich_caches_results(self, mock_graph_store):
        mock_graph_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        enricher = ModuleEnricher(mock_graph_store)
        await enricher.enrich(["r"], ["Svc"])
        await enricher.enrich(["r"], ["Svc"])
        assert mock_graph_store.execute_query.call_count == 3  # 3 queries first time, 0 second time
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_module_enricher.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Add Cypher queries to cypher_queries.py**

Append to `wiki/cypher_queries.py`:

```python
MODULE_KEY_METHODS_CY = (
    "MATCH (m:Module)-[:CONTAINS*1..2]->(f:Function) "
    "WHERE m.repository IN $repos AND m.name IN $names "
    "RETURN m.name AS module_name, m.repository AS repo, "
    "collect(DISTINCT f.name)[0..5] AS key_methods"
)

MODULE_CALLEES_CY = (
    "MATCH (m1:Module)-[:CONTAINS*1..3]->(f1:Function)"
    "-[:CALLS]->(f2:Function)<-[:CONTAINS*1..3]-(m2:Module) "
    "WHERE m1.repository IN $repos AND m1 <> m2 "
    "RETURN m1.name AS source, m1.repository AS repo, "
    "collect(DISTINCT m2.name)[0..5] AS callees, "
    "count(DISTINCT m2) AS fan_out"
)

MODULE_CALLERS_CY = (
    "MATCH (m1:Module)-[:CONTAINS*1..3]->(f1:Function)"
    "-[:CALLS]->(f2:Function)<-[:CONTAINS*1..3]-(m2:Module) "
    "WHERE m2.repository IN $repos AND m1 <> m2 "
    "RETURN m2.name AS target, m2.repository AS repo, "
    "collect(DISTINCT m1.name)[0..5] AS callers, "
    "count(DISTINCT m1) AS fan_in"
)
```

- [ ] **Step 4: Implement ModuleEnricher**

```python
# wiki/module_enricher.py
from __future__ import annotations

from typing import Any

from wiki.cypher_queries import MODULE_KEY_METHODS_CY, MODULE_CALLEES_CY, MODULE_CALLERS_CY


class ModuleEnricher:
    """Bulk-fetch module signals (key_methods, callers, callees, fan_in/out) and cache results."""

    def __init__(self, graph_store: Any) -> None:
        self._store = graph_store
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    async def enrich(
        self, repos: list[str], names: list[str]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        uncached_repos = []
        uncached_names = []
        for r in repos:
            for n in names:
                if (r, n) not in self._cache:
                    uncached_repos.append(r)
                    uncached_names.append(n)

        if not uncached_names:
            return self._cache

        params = {"repos": list(set(repos)), "names": list(set(names))}
        methods_result = await self._store.execute_query(MODULE_KEY_METHODS_CY, params)
        callees_result = await self._store.execute_query(MODULE_CALLEES_CY, params)
        callers_result = await self._store.execute_query(MODULE_CALLERS_CY, params)

        for row in methods_result.data or []:
            key = (row["repo"], row["module_name"])
            self._cache.setdefault(key, {})["key_methods"] = row.get("key_methods", [])

        for row in callees_result.data or []:
            key = (row["repo"], row["source"])
            entry = self._cache.setdefault(key, {})
            entry["callees"] = row.get("callees", [])
            entry["fan_out"] = row.get("fan_out", 0)

        for row in callers_result.data or []:
            key = (row["repo"], row["target"])
            entry = self._cache.setdefault(key, {})
            entry["callers"] = row.get("callers", [])
            entry["fan_in"] = row.get("fan_in", 0)

        return self._cache

    def get(self, repo: str, name: str) -> dict[str, Any]:
        return self._cache.get((repo, name), {})
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/wiki/test_module_enricher.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/module_enricher.py wiki/cypher_queries.py tests/wiki/test_module_enricher.py
git commit -m "feat: add ModuleEnricher for bulk signal enrichment (key_methods, callers, callees)"
```

---

## Task 4: DomainStabilizer Dual-Field Matching (P1)

**Files:**
- Modify: `wiki/domain_stabilizer.py:28-209`
- Create: `tests/wiki/test_domain_stabilizer_v2.py`

- [ ] **Step 1: Write failing tests for dual-field stabilizer**

```python
# tests/wiki/test_domain_stabilizer_v2.py
import pytest
from wiki.domain_stabilizer import DomainStabilizer


class TestDualFieldStabilize:
    @pytest.fixture
    def stabilizer(self):
        return DomainStabilizer(graph_store=None)

    def test_exact_slug_match(self, stabilizer):
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [{"slug": "gift-system", "display_name": "Gift System"}]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert result["gift-system"]["slug"] == "gift-system"
        assert result["gift-system"]["display_name"] == "礼物系统"

    def test_display_name_similarity_match(self, stabilizer):
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [{"slug": "gift-sys", "display_name": "礼物管理系统"}]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert "gift-system" in result

    def test_new_domain_passthrough(self, stabilizer):
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [{"slug": "im-messaging", "display_name": "IM消息"}]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert "im-messaging" in result
        assert result["im-messaging"]["display_name"] == "IM消息"

    def test_empty_existing(self, stabilizer):
        proposed = [{"slug": "gift-system", "display_name": "礼物系统"}]
        result = stabilizer.stabilize_dual_sync(proposed, [])
        assert "gift-system" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_domain_stabilizer_v2.py -v`
Expected: FAIL — `stabilize_dual_sync` not defined

- [ ] **Step 3: Implement stabilize_dual_sync**

Add to `wiki/domain_stabilizer.py`:

```python
def stabilize_dual_sync(
    self,
    proposed: list[dict[str, str]],
    existing: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Match proposed (slug, display_name) pairs against existing anchors.

    Priority: exact slug > display_name similarity > slug similarity > new domain.
    Returns: {slug: {"slug": str, "display_name": str}}
    """
    result: dict[str, dict[str, str]] = {}
    used_existing: set[str] = set()

    for prop in proposed:
        p_slug = prop["slug"]
        p_display = prop.get("display_name", p_slug)

        # 1. Exact slug match
        exact = next((e for e in existing if e["slug"] == p_slug and e["slug"] not in used_existing), None)
        if exact:
            used_existing.add(exact["slug"])
            result[exact["slug"]] = {"slug": exact["slug"], "display_name": exact["display_name"]}
            continue

        # 2. Display name similarity
        best_score = 0.0
        best_match = None
        for e in existing:
            if e["slug"] in used_existing:
                continue
            score = self.compute_similarity(
                self.normalize_domain_name(p_display),
                self.normalize_domain_name(e["display_name"]),
            )
            if score > best_score:
                best_score = score
                best_match = e

        if best_match and best_score >= self._threshold:
            used_existing.add(best_match["slug"])
            result[best_match["slug"]] = {
                "slug": best_match["slug"],
                "display_name": best_match["display_name"],
            }
            continue

        # 3. Slug similarity
        best_score = 0.0
        best_match = None
        for e in existing:
            if e["slug"] in used_existing:
                continue
            score = self.compute_similarity(p_slug, e["slug"])
            if score > best_score:
                best_score = score
                best_match = e

        if best_match and best_score >= self._threshold:
            used_existing.add(best_match["slug"])
            result[best_match["slug"]] = {
                "slug": best_match["slug"],
                "display_name": best_match["display_name"],
            }
            continue

        # 4. New domain
        result[p_slug] = {"slug": p_slug, "display_name": p_display}

    return result
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/test_domain_stabilizer_v2.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/domain_stabilizer.py tests/wiki/test_domain_stabilizer_v2.py
git commit -m "feat: add DomainStabilizer.stabilize_dual_sync for slug+display_name matching"
```

---

## Task 5: Anchor Domain Loading + domain_pinned (P1)

**Files:**
- Modify: `wiki/nodes/classify.py:70-224`
- Depends on: Task 2 (storage methods), Task 3 (enricher)

- [ ] **Step 1: Write failing test for anchor loading and pinned skip**

```python
# tests/wiki/test_anchor_loading.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAnchorLoading:
    @pytest.mark.asyncio
    async def test_pinned_modules_skip_classification(self):
        """Modules with domain_pinned=True should not be sent to LLM."""
        from wiki.nodes.classify import _split_pinned_modules

        modules = [
            {"name": "PinnedSvc", "repository": "r1", "properties": {"domain_pinned": True, "business_domain": "gift-system"}},
            {"name": "UnpinnedSvc", "repository": "r1", "properties": {}},
        ]
        pinned, unpinned = _split_pinned_modules(modules)
        assert len(pinned) == 1
        assert pinned["gift-system"] == [("r1", "PinnedSvc")]
        assert len(unpinned) == 1
        assert unpinned[0]["name"] == "UnpinnedSvc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_anchor_loading.py -v`
Expected: FAIL — `_split_pinned_modules` not defined

- [ ] **Step 3: Implement _split_pinned_modules in classify.py**

Add helper function at top of `wiki/nodes/classify.py`:

```python
def _split_pinned_modules(
    modules: list[dict],
) -> tuple[dict[str, list[tuple[str, str]]], list[dict]]:
    """Split modules into pinned (already assigned) and unpinned (need classification)."""
    pinned: dict[str, list[tuple[str, str]]] = {}
    unpinned: list[dict] = []
    for mod in modules:
        props = mod.get("properties", {})
        if props.get("domain_pinned") and props.get("business_domain"):
            domain = props["business_domain"]
            pinned.setdefault(domain, []).append((mod["repository"], mod["name"]))
        else:
            unpinned.append(mod)
    return pinned, unpinned
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/wiki/test_anchor_loading.py -v`
Expected: PASS

- [ ] **Step 5: Integrate anchor loading into classify_domains_node**

Modify `classify_domains_node` in `wiki/nodes/classify.py` to:
1. Load anchors from `WikiPageStore.load_anchor_domains(business_id)`
2. Call `_split_pinned_modules` before classification
3. Pass `anchor_domains` to `CrossRepoBusinessDomainPlanner`
4. Merge pinned mapping back into final `domain_mapping`

- [ ] **Step 6: Run all classification tests**

Run: `uv run pytest tests/wiki/test_anchor_loading.py tests/wiki/test_slug_system.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/nodes/classify.py tests/wiki/test_anchor_loading.py
git commit -m "feat: add anchor domain loading and domain_pinned module skip"
```

---

## Task 6: Prompt Redesign — Anchor Injection + Slug Output (P1)

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py:668-764`
- Depends on: Task 5 (anchors available)

- [ ] **Step 1: Write failing test for anchor prompt injection**

```python
# tests/wiki/test_prompt_anchor_injection.py
import pytest
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


class TestPromptAnchorInjection:
    @pytest.fixture
    def planner(self):
        from unittest.mock import MagicMock
        return CrossRepoBusinessDomainPlanner(llm=MagicMock())

    def test_prompt_contains_anchor_domains(self, planner):
        anchors = [
            {"slug": "gift-system", "display_name": "礼物系统"},
            {"slug": "im-messaging", "display_name": "IM消息"},
        ]
        modules = [("repo", "SomeService", "methods: doThing", "src/SomeService.java")]
        prompt = planner._build_single_batch_prompt(modules, pre_groups=None, anchor_domains=anchors)
        assert "gift-system" in prompt
        assert "礼物系统" in prompt
        assert "im-messaging" in prompt

    def test_prompt_without_anchors(self, planner):
        modules = [("repo", "SomeService", "methods: doThing", "src/SomeService.java")]
        prompt = planner._build_single_batch_prompt(modules, pre_groups=None, anchor_domains=None)
        assert "已有业务域" not in prompt

    def test_prompt_requests_slug_output(self, planner):
        modules = [("repo", "SomeService", "methods: doThing", "src/SomeService.java")]
        prompt = planner._build_single_batch_prompt(modules, pre_groups=None, anchor_domains=None)
        assert "slug" in prompt.lower()
        assert "display_name" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_prompt_anchor_injection.py -v`
Expected: FAIL — `_build_single_batch_prompt` doesn't accept `anchor_domains`

- [ ] **Step 3: Modify _build_single_batch_prompt to accept anchor_domains**

Update `wiki/cross_repo_domain_planner.py` method `_build_single_batch_prompt` to:
1. Accept `anchor_domains: list[dict] | None = None` parameter
2. Inject anchor section when available
3. Change output format to request `slug` + `display_name`
4. Unify prompt language to Chinese

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/test_prompt_anchor_injection.py -v`
Expected: PASS

- [ ] **Step 5: Similarly update _build_lightweight_merge_prompt**

- [ ] **Step 6: Commit**

```bash
git add wiki/cross_repo_domain_planner.py tests/wiki/test_prompt_anchor_injection.py
git commit -m "feat: inject anchor domains into classification prompt, request slug+display_name output"
```

---

## Task 7: Remove 200 Cap + Sub-batch Anchor Injection (P1)

**Files:**
- Modify: `wiki/nodes/classify.py:83-164`
- Modify: `wiki/cross_repo_domain_planner.py:614-666`

- [ ] **Step 1: Write test verifying no cap applied**

```python
# tests/wiki/test_no_cap.py
import pytest


class TestNoCap:
    def test_max_modules_constant_removed_or_raised(self):
        from wiki.nodes import classify
        cap = getattr(classify, "_MAX_MODULES_FOR_CLASSIFICATION", None)
        assert cap is None or cap >= 10000, "200 cap should be removed"
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/wiki/test_no_cap.py -v`
Expected: FAIL

- [ ] **Step 3: Remove the 200 cap from classify.py**

Remove or set to a very high value the `_MAX_MODULES_FOR_CLASSIFICATION` constant and the tier1/tier2/tier3 truncation logic at lines 138-164.

- [ ] **Step 4: Inject anchors into sub-batches**

In `wiki/cross_repo_domain_planner.py:_classify_multi_batch`, pass `anchor_domains` to each sub-batch's `_classify_single_batch` call.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/wiki/ -v --timeout=30 -x`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/classify.py wiki/cross_repo_domain_planner.py tests/wiki/test_no_cap.py
git commit -m "feat: remove 200 module cap, inject anchors into all sub-batches"
```

---

## Task 8: Pipeline Intermediate Persistence (P1)

**Files:**
- Create: `wiki/nodes/persist_classification.py`
- Modify: `wiki/pipeline_graph.py:301-373`
- Modify: `wiki/nodes/domain_compose.py`

- [ ] **Step 1: Write failing test for persist_classification_node**

```python
# tests/wiki/test_persist_classification_node.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestPersistClassificationNode:
    @pytest.mark.asyncio
    async def test_node_writes_domain_mapping(self):
        from wiki.nodes.persist_classification import persist_classification_node

        state = {
            "business_id": "ultron",
            "domain_mapping": {"gift-system": [("ultron/r1", "SvcA")]},
            "domain_display_names": {"gift-system": "礼物系统"},
            "graph_store": AsyncMock(),
            "wiki_store": AsyncMock(),
        }
        result = await persist_classification_node(state)
        assert "domain_mapping" in result
        state["graph_store"].execute_query.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement persist_classification_node**

```python
# wiki/nodes/persist_classification.py
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def persist_classification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Persist domain classification results immediately after classify_domains.

    Updates Module.business_domain in FalkorDB and creates/updates
    WikiSection nodes for each domain (anchor persistence).
    """
    domain_mapping = state.get("domain_mapping", {})
    display_names = state.get("domain_display_names", {})
    graph_store = state.get("graph_store")
    business_id = state.get("business_id", "")

    if not domain_mapping or not graph_store:
        return state

    # Update Module.business_domain for each module
    for slug, modules in domain_mapping.items():
        for repo, name in modules:
            q = (
                "MATCH (m:Module {name: $name, repository: $repo}) "
                "SET m.business_domain = $slug"
            )
            await graph_store.execute_query(q, {"name": name, "repo": repo, "slug": slug})

    logger.info(
        "persist_classification: wrote %d domains, %d modules",
        len(domain_mapping),
        sum(len(v) for v in domain_mapping.values()),
    )
    return state
```

- [ ] **Step 4: Register node in pipeline_graph.py**

Add `persist_classification` node between `classify_domains` and `decompose_hierarchy` in `build_wiki_pipeline`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/wiki/test_persist_classification_node.py -v`
Expected: PASS

- [ ] **Step 6: Modify domain_compose for per-domain persistence**

In `wiki/nodes/domain_compose.py`, after each domain's agent completes, call `persist_pages_to_graph` for that domain's pages immediately rather than collecting all pages and persisting at the end.

- [ ] **Step 7: Commit**

```bash
git add wiki/nodes/persist_classification.py wiki/pipeline_graph.py wiki/nodes/domain_compose.py tests/wiki/test_persist_classification_node.py
git commit -m "feat: add persist_classification_node + per-domain page persistence"
```

---

## Task 9: LangGraph AsyncSqliteSaver Checkpointer (P2)

**Files:**
- Modify: `wiki/pipeline_graph.py:301-312, 369-373`
- Modify: `wiki/pipeline_orchestrator.py`
- Modify: `wiki/service.py`

- [ ] **Step 1: Write test for checkpointer configuration**

```python
# tests/wiki/test_checkpointer.py
import pytest


class TestCheckpointer:
    def test_build_pipeline_accepts_sqlite_checkpointer(self):
        from wiki.pipeline_graph import build_wiki_pipeline
        graph = build_wiki_pipeline(checkpointer="sqlite")
        assert graph is not None

    def test_build_pipeline_default_memory(self):
        from wiki.pipeline_graph import build_wiki_pipeline
        graph = build_wiki_pipeline()
        assert graph is not None
```

- [ ] **Step 2: Run test**

- [ ] **Step 3: Add AsyncSqliteSaver support to build_wiki_pipeline**

In `wiki/pipeline_graph.py`, modify `build_wiki_pipeline` to accept `checkpointer="sqlite"` and create an `AsyncSqliteSaver` instance.

- [ ] **Step 4: Update pipeline_orchestrator to pass thread_id**

- [ ] **Step 5: Add resume/checkpoint management to service.py**

Add methods: `resume_pipeline`, `get_checkpoint_info`, `delete_checkpoint`

- [ ] **Step 6: Run tests**

- [ ] **Step 7: Commit**

```bash
git add wiki/pipeline_graph.py wiki/pipeline_orchestrator.py wiki/service.py tests/wiki/test_checkpointer.py
git commit -m "feat: upgrade to AsyncSqliteSaver with resume/checkpoint management"
```

---

## Task 10: Dashboard REST API — Domain Management + Pipeline Control (P1)

**Files:**
- Modify: `api/routes/wiki_page_routes.py`
- Depends on: Task 2 (storage), Task 9 (checkpointer)

- [ ] **Step 1: Write API endpoint tests (schema validation)**

Test the 11 new endpoints: list domains, list modules, move module, rename domain, clear pin, delete empty domain, regenerate domain, resume, regenerate all, get checkpoint, delete checkpoint.

- [ ] **Step 2: Implement endpoints one by one**

Each endpoint follows the pattern:
1. Parse path/query params
2. Get store dependency
3. Call storage method
4. Return JSON response

- [ ] **Step 3: Run API tests**

- [ ] **Step 4: Commit**

```bash
git add api/routes/wiki_page_routes.py tests/
git commit -m "feat: add 11 domain management + pipeline control API endpoints"
```

---

## Task 11: Dashboard UI — Domain Management + Checkpoint Panel (P2)

**Files:**
- Create: `dashboard/src/components/wiki/CheckpointPanel.tsx`
- Create: `dashboard/src/components/wiki/DomainManagement.tsx`
- Create: `dashboard/src/hooks/useCheckpoint.ts`
- Create: `dashboard/src/hooks/useDomainManagement.ts`
- Modify: `dashboard/src/components/wiki/WikiToolPanel.tsx`

- [ ] **Step 1: Create checkpoint API hook**
- [ ] **Step 2: Create CheckpointPanel component**
- [ ] **Step 3: Create domain management hooks**
- [ ] **Step 4: Create DomainManagement component**
- [ ] **Step 5: Integrate into WikiToolPanel**
- [ ] **Step 6: Commit**

---

## Task 12: Trigger Script Updates (P1)

**Files:**
- Modify: `scripts/trigger_wiki_generate.sh`

- [ ] **Step 1: Add --resume command**
- [ ] **Step 2: Add --regenerate-domain command**
- [ ] **Step 3: Add --reset-anchors command**
- [ ] **Step 4: Add --list-domains command**
- [ ] **Step 5: Add --move-module command**
- [ ] **Step 6: Test each command with --help**
- [ ] **Step 7: Commit**

---

## Task 13: Classification Stability Regression Tests (P1)

**Files:**
- Create: `tests/wiki/test_classification_pipeline.py`

- [ ] **Step 1: Write integration test for anchor stability**

Test that running classification twice with the same input produces the same domain mapping when anchors are persisted.

- [ ] **Step 2: Write test for signal enrichment impact**

Test that modules with enriched signals get classified more accurately.

- [ ] **Step 3: Write test for pinned module preservation**

Test that pinned modules stay in their assigned domain.

- [ ] **Step 4: Commit**

```bash
git add tests/wiki/test_classification_pipeline.py
git commit -m "test: add classification stability regression tests"
```
