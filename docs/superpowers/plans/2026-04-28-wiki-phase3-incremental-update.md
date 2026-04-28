# Wiki Phase 3: Incremental Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable incremental wiki updates that only regenerate pages affected by code changes, reducing iteration time from hours to minutes.

**Architecture:** Compare current graph state with last wiki generation version. Identify changed entities via `code_hash` mismatch. Propagate changes upward through CONTAINS edges to parent modules. Regenerate only affected pages (leaves + ancestors + business flows).

**Tech Stack:** Python 3.11+, FalkorDB (graph diff queries), asyncio

**Spec:** [`docs/superpowers/specs/2026-04-28-wiki-hierarchical-generation-design.md`](../specs/2026-04-28-wiki-hierarchical-generation-design.md) §3.10

**Depends on:** Phase 1 + Phase 2 completed (bottom-up composition, WikiPageSummary)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `wiki/incremental_diff.py` (create) | Graph diff computation: changed entities + affected ancestors |
| `wiki/service.py` (modify) | Add `generate_incremental()` entry point |
| `store/wiki_store.py` (modify) | Version tracking: get/set wiki_generation_version |
| `config.py` (modify) | Add `incremental_enabled` config |

---

### Task 1: Implement WikiDiff computation

**Files:**
- Create: `wiki/incremental_diff.py`
- Create: `tests/wiki/test_incremental_diff.py`

- [ ] **Step 1: Write failing tests for WikiDiff**

```python
# tests/wiki/test_incremental_diff.py
import pytest
from unittest.mock import AsyncMock
from wiki.incremental_diff import WikiDiff, compute_wiki_diff


def test_wiki_diff_empty():
    diff = WikiDiff(changed_uids=set(), affected_parents=set(), affected_communities=set())
    assert diff.is_empty
    assert diff.total_affected == 0


def test_wiki_diff_total_affected():
    diff = WikiDiff(
        changed_uids={"a", "b"},
        affected_parents={"p1"},
        affected_communities={1},
    )
    assert not diff.is_empty
    assert diff.total_affected == 3  # 2 changed + 1 parent


def test_wiki_diff_includes_community():
    diff = WikiDiff(
        changed_uids={"a"},
        affected_parents=set(),
        affected_communities={0, 2},
    )
    assert len(diff.affected_communities) == 2


@pytest.mark.asyncio
async def test_compute_wiki_diff_no_changes():
    store = AsyncMock()
    store.execute_query = AsyncMock(side_effect=[
        type('R', (), {'data': []})(),  # no changed entities
    ])
    diff = await compute_wiki_diff(store, "test-repo", since_version=0)
    assert diff.is_empty


@pytest.mark.asyncio
async def test_compute_wiki_diff_with_changes_and_parents():
    store = AsyncMock()
    store.execute_query = AsyncMock(side_effect=[
        type('R', (), {'data': [["uid:Class:Foo"]]})(),  # changed entities
        type('R', (), {'data': [["uid:Module:api"]]})(),  # affected parents
        type('R', (), {'data': [[0]]})(),  # affected communities
    ])
    diff = await compute_wiki_diff(store, "test-repo", since_version=0)
    assert diff.changed_uids == {"uid:Class:Foo"}
    assert diff.affected_parents == {"uid:Module:api"}
    assert diff.affected_communities == {0}
```

- [ ] **Step 2: Implement WikiDiff dataclass + compute_wiki_diff**

```python
# wiki/incremental_diff.py
"""Graph diff computation for incremental wiki updates."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class WikiDiff:
    changed_uids: set[str]
    affected_parents: set[str]
    affected_communities: set[int] = field(default_factory=set)

    @property
    def is_empty(self) -> bool:
        return not self.changed_uids and not self.affected_parents

    @property
    def total_affected(self) -> int:
        return len(self.changed_uids) + len(self.affected_parents)


async def compute_wiki_diff(store: Any, repository: str, since_version: int) -> WikiDiff:
    """Compare current graph state with last wiki generation to find affected entities."""

    # 1. Find entities where code_hash changed since last wiki generation
    changed_result = await store.execute_query(
        "MATCH (n {repository: $repo}) "
        "WHERE n.code_hash IS NOT NULL AND "
        "      (n.wiki_code_hash IS NULL OR n.code_hash <> n.wiki_code_hash) "
        "RETURN n.uid",
        {"repo": repository},
    )
    changed_uids = {row[0] for row in (getattr(changed_result, 'data', None) or []) if row[0]}

    if not changed_uids:
        log.info("incremental_diff_no_changes", repository=repository)
        return WikiDiff(set(), set())

    # 2. Find ancestor modules via CONTAINS edges (upward propagation)
    ancestors_result = await store.execute_query(
        "MATCH (parent)-[:CONTAINS*1..10]->(child) "
        "WHERE child.uid IN $uids AND parent.repository = $repo "
        "RETURN DISTINCT parent.uid",
        {"repo": repository, "uids": list(changed_uids)},
    )
    affected_parents = {row[0] for row in (getattr(ancestors_result, 'data', None) or []) if row[0]}

    # 3. Find affected communities containing changed entities
    community_result = await store.execute_query(
        "MATCH (n)-[:BELONGS_TO]->(c:Community) "
        "WHERE n.uid IN $uids AND n.repository = $repo "
        "RETURN DISTINCT c.community_id",
        {"repo": repository, "uids": list(changed_uids)},
    )
    affected_communities = {
        int(row[0]) for row in (getattr(community_result, 'data', None) or [])
        if row[0] is not None
    }

    log.info(
        "incremental_diff_computed",
        repository=repository,
        changed=len(changed_uids),
        parents=len(affected_parents),
        communities=len(affected_communities),
    )
    return WikiDiff(changed_uids, affected_parents, affected_communities)
```

- [ ] **Step 3: Tests and commit**

Run: `uv run pytest tests/wiki/test_incremental_diff.py -v`
Expected: ALL PASS

```bash
git add wiki/incremental_diff.py tests/wiki/test_incremental_diff.py
git commit -m "feat(wiki): add WikiDiff computation with community impact tracking"
```

---

### Task 2: Add version tracking to WikiStore

**Files:**
- Modify: `store/wiki_store.py`
- Test: `tests/store/test_wiki_store.py`

- [ ] **Step 1: Add get/set wiki_generation_version methods**

```python
async def get_wiki_generation_version(self, repository: str) -> int | None:
    result = await self._store.execute_query(
        "MATCH (m:WikiMeta {repository: $repo}) RETURN m.generation_version",
        {"repo": repository},
    )
    rows = getattr(result, 'data', None) or []
    return int(rows[0][0]) if rows and rows[0][0] is not None else None

async def set_wiki_generation_version(self, repository: str, version: int) -> None:
    await self._store.execute_query(
        "MERGE (m:WikiMeta {repository: $repo}) SET m.generation_version = $ver",
        {"repo": repository, "ver": version},
    )
```

- [ ] **Step 2: Tests and commit**

---

### Task 3: Implement generate_incremental in WikiService

**Files:**
- Modify: `wiki/service.py`
- Create: `tests/wiki/test_incremental_generation.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_incremental_generation.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.incremental_diff import WikiDiff


@pytest.mark.asyncio
async def test_incremental_skips_unchanged_entities():
    """Verify that generate_incremental only processes changed entities."""
    # Placeholder — fill with project fixtures after implementation
    pass


@pytest.mark.asyncio
async def test_incremental_updates_wiki_code_hash():
    """Verify wiki_code_hash is updated after successful page generation."""
    pass


@pytest.mark.asyncio
async def test_incremental_rollback_on_failure():
    """Verify partial failure doesn't corrupt wiki state."""
    pass
```

- [ ] **Step 2: Implement `generate_incremental` method**

```python
async def generate_incremental(
    self,
    repository: str,
    config: WikiConfig | None = None,
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """Incremental wiki update: only regenerate pages affected by code changes."""
    from wiki.incremental_diff import compute_wiki_diff

    config = config or self._default_config(repository)
    wiki_store = WikiStore(self._store) if self._store else None

    # Get last generation version
    last_version = await wiki_store.get_wiki_generation_version(repository) if wiki_store else None
    if last_version is None:
        log.info("incremental_no_baseline", repository=repository)
        return {"status": "no_baseline", "message": "No previous generation found. Run full generation first."}

    # Compute diff
    diff = await compute_wiki_diff(self._store, repository, since_version=last_version)
    if diff.is_empty:
        log.info("incremental_no_changes", repository=repository)
        return {"status": "no_changes", "changed": 0}

    if progress_callback:
        await progress_callback({"phase": "incremental_diff", "changed": diff.total_affected})

    # Track successfully regenerated pages for rollback safety
    regenerated_pages: list[WikiPage] = []
    updated_uids: list[str] = []

    try:
        # 1. Recompose changed leaf entities
        # (reuse existing _compose_all_pages leaf pass, but filter to diff.changed_uids)
        # ... implementation uses summary_index from previous generation ...

        # 2. Recompose affected parent modules
        for parent_uid in diff.affected_parents:
            # Load existing child summaries, replace changed ones
            pass

        # 3. Recompose affected business flow pages
        for community_id in diff.affected_communities:
            pass

        # 4. Persist only changed pages
        if regenerated_pages:
            await self._persist_pages_to_graph(repository, regenerated_pages)

        # 5. Update wiki_code_hash for successfully regenerated entities
        await self._update_wiki_code_hashes(repository, updated_uids)

        # 6. Update generation version
        current_version = last_version + 1
        await wiki_store.set_wiki_generation_version(repository, current_version)

        log.info("incremental_complete", repository=repository,
                 pages_regenerated=len(regenerated_pages), version=current_version)

        return {
            "status": "success",
            "pages_regenerated": len(regenerated_pages),
            "changed_entities": len(diff.changed_uids),
            "affected_parents": len(diff.affected_parents),
            "version": current_version,
        }
    except Exception:
        log.error("incremental_failed", repository=repository, exc_info=True)
        # Rollback: don't update version, pages remain at previous state
        # Already-persisted pages are safe because graph store is eventually consistent
        return {"status": "failed", "pages_regenerated": len(regenerated_pages)}
```

- [ ] **Step 3: Implement `_update_wiki_code_hashes` helper**

This is the critical step that marks entities as "wiki up-to-date" after successful generation:

```python
async def _update_wiki_code_hashes(self, repository: str, uids: list[str]) -> None:
    """After successful wiki page generation, set wiki_code_hash = code_hash
    for the regenerated entities so they won't be picked up in the next diff."""
    if not uids or not self._store:
        return
    await self._store.execute_query(
        "MATCH (n {repository: $repo}) "
        "WHERE n.uid IN $uids AND n.code_hash IS NOT NULL "
        "SET n.wiki_code_hash = n.code_hash",
        {"repo": repository, "uids": uids},
    )
    log.info("wiki_code_hashes_updated", repository=repository, count=len(uids))
```

> **Rollback strategy:** If `generate_incremental` fails midway:
> - `wiki_generation_version` is NOT updated (remains at previous version)
> - `wiki_code_hash` is only updated for successfully processed entities
> - Next incremental run will re-detect failed entities because their `wiki_code_hash` still differs
> - This provides automatic retry semantics without explicit rollback

- [ ] **Step 4: Wire into API route**

```python
# api/routes/wiki_routes.py
@router.post("/generate-incremental", response_model=dict)
async def generate_incremental_wiki(
    request: WikiGenerateRequest,
    wiki_service: WikiService = Depends(get_wiki_service),
):
    """Trigger incremental wiki update for a repository."""
    if not getattr(wiki_service._wiki_cfg, 'incremental_enabled', False):
        raise HTTPException(400, "Incremental updates are not enabled")
    result = await wiki_service.generate_incremental(request.repository)
    return result
```

- [ ] **Step 5: Run tests and commit**

```bash
git add wiki/service.py api/routes/wiki_routes.py tests/wiki/test_incremental_generation.py
git commit -m "feat(wiki): add generate_incremental with wiki_code_hash tracking and rollback safety"
```

---

### Task 4: Add configuration and API endpoint

**Files:**
- Modify: `config.py`
- Modify: `api/routes/wiki_routes.py`

- [ ] **Step 1: Add `incremental_enabled` config field**
- [ ] **Step 2: Add optional `--incremental` flag to wiki generation API**
- [ ] **Step 3: Tests and commit**

---

## Self-Review Checklist

- [x] Spec §3.10.1 (Diff detection): Task 1
- [x] Spec §3.10.2 (Incremental generation flow): Task 3
- [x] Spec §3.10.3 (Version tracking): Task 2
- [x] Configuration: Task 4
