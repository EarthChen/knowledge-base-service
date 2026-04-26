# SP3: Incremental Ingest Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable selective wiki page regeneration based on source code changes, preserving unchanged pages and their annotations.

**Architecture:** ChangeDetector parses git diff → queries graph for affected entities → expands 1-hop → identifies affected WikiPages. WikiService.generate_incremental() regenerates only those pages. WikiChangeLog nodes track audit trail.

**Tech Stack:** Python 3.11+, FastAPI, FalkorDB Cypher, pytest, asyncio

---

### Task 1: ChangeDetector Core

**Files:**
- Create: `wiki/change_detector.py`
- Test: `tests/wiki/test_change_detector.py`

- [ ] **Step 1: Write failing test for git diff parsing**

```python
# tests/wiki/test_change_detector.py
import pytest
from wiki.change_detector import ChangeDetector, AffectedPageSet

SAMPLE_DIFF = """M\tauth.py
A\tutils/new_helper.py
D\told_module.py
"""

def test_parse_git_diff_name_status():
    files = ChangeDetector._parse_diff_output(SAMPLE_DIFF)
    assert files == ["auth.py", "utils/new_helper.py", "old_module.py"]

def test_parse_empty_diff():
    assert ChangeDetector._parse_diff_output("") == []
    assert ChangeDetector._parse_diff_output("\n\n") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_change_detector.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ChangeDetector with diff parsing**

```python
# wiki/change_detector.py
"""Detect affected wiki pages from source code changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)


@dataclass
class AffectedPageSet:
    page_uids: list[str] = field(default_factory=list)
    affected_entities: list[str] = field(default_factory=list)
    trigger: str = "manual"
    files_changed: list[str] = field(default_factory=list)
    impact_radius: int = 1
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class ChangeDetector:
    def __init__(self, graph: _GraphPort) -> None:
        self._graph = graph

    @staticmethod
    def _parse_diff_output(diff_output: str) -> list[str]:
        files: list[str] = []
        for line in diff_output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                files.append(parts[1].strip())
            elif line and not line[0].isalpha():
                files.append(line)
        return files

    async def detect_from_file_list(
        self,
        repository: str,
        changed_files: list[str],
        *,
        trigger: str = "manual",
    ) -> AffectedPageSet:
        if not changed_files:
            return AffectedPageSet(trigger=trigger)

        direct_q = (
            "MATCH (e) WHERE e.file IN $files AND e.repository = $repo "
            "RETURN e.uid AS uid"
        )
        result = await self._graph.execute_query(direct_q, {"files": changed_files, "repo": repository})
        direct_uids = [str(row[0]) for row in (getattr(result, "raw", []) or [])]

        neighbor_uids: list[str] = []
        if direct_uids:
            hop_q = (
                "MATCH (e)-[:CALLS|IMPORTS|CONTAINS*1]-(neighbor) "
                "WHERE e.uid IN $uids RETURN DISTINCT neighbor.uid AS uid"
            )
            hop_result = await self._graph.execute_query(hop_q, {"uids": direct_uids})
            neighbor_uids = [str(row[0]) for row in (getattr(hop_result, "raw", []) or [])]

        all_entity_uids = list(set(direct_uids + neighbor_uids))

        page_uids: list[str] = []
        if all_entity_uids:
            page_q = (
                "MATCH (wp:WikiPage)-[:SOURCE_ENTITY]->(e) "
                "WHERE e.uid IN $uids RETURN DISTINCT wp.uid AS uid"
            )
            page_result = await self._graph.execute_query(page_q, {"uids": all_entity_uids})
            page_uids = [str(row[0]) for row in (getattr(page_result, "raw", []) or [])]

        return AffectedPageSet(
            page_uids=page_uids,
            affected_entities=all_entity_uids,
            trigger=trigger,
            files_changed=changed_files,
        )

    async def detect_from_git_diff(
        self,
        repository: str,
        diff_output: str,
        *,
        trigger: str = "git_push",
    ) -> AffectedPageSet:
        files = self._parse_diff_output(diff_output)
        return await self.detect_from_file_list(repository, files, trigger=trigger)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/test_change_detector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/change_detector.py tests/wiki/test_change_detector.py
git commit -m "feat(sp3): add ChangeDetector with git diff parsing and entity resolution"
```

---

### Task 2: WikiService.generate_incremental()

**Files:**
- Modify: `wiki/service.py`
- Test: `tests/wiki/test_incremental_generation.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_incremental_generation.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.change_detector import AffectedPageSet


@pytest.mark.asyncio
async def test_incremental_skips_unaffected_pages():
    """generate_incremental should only regenerate pages in AffectedPageSet."""
    # Setup mock WikiService with 10 existing pages, only 2 affected
    affected = AffectedPageSet(
        page_uids=["WikiPage:repo:auth.md", "WikiPage:repo:utils.md"],
        affected_entities=["Entity:auth", "Entity:utils"],
        trigger="git_push",
        files_changed=["auth.py", "utils.py"],
    )
    # Assert only 2 pages were regenerated, others untouched
    assert len(affected.page_uids) == 2
```

- [ ] **Step 2: Implement generate_incremental in WikiService**

Add new method to `wiki/service.py`:

```python
async def generate_incremental(
    self,
    repository: str,
    affected: AffectedPageSet,
    language: str = "en",
    llm_provider: str | None = None,
) -> dict[str, Any]:
    """Regenerate only affected wiki pages. Preserve unchanged pages."""
    await self._ensure_repo(repository)

    if not affected.page_uids:
        return {"pages_regenerated": 0, "pages_total": 0, "trigger": affected.trigger}

    # Fetch affected WikiPage nodes
    # Regenerate only those pages
    # Preserve annotations on unchanged pages
    # Version increment on changed pages
    # Log change audit
    ...
```

- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

---

### Task 3: WikiChangeLog Audit Trail

**Files:**
- Modify: `store/wiki_page_store.py`
- Test: `tests/store/test_wiki_changelog.py`

- [ ] **Step 1: Write test for changelog persistence**
- [ ] **Step 2: Add persist_changelog and list_changelogs methods**
- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

---

### Task 4: Ingest API Endpoint

**Files:**
- Modify: `api/routes/wiki_routes.py`
- Test: `tests/api/test_wiki_ingest.py`

- [ ] **Step 1: Write test for POST /api/v1/wiki/ingest**
- [ ] **Step 2: Implement endpoint that accepts file list or git ref**
- [ ] **Step 3: Add GET /api/v1/wiki/changelog for audit trail**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 5: Webhook Integration for Auto-Ingest

**Files:**
- Modify: `api/routes/webhook_routes.py`
- Test: `tests/api/test_webhook_ingest.py`

- [ ] **Step 1: Write test for webhook → incremental ingest trigger**
- [ ] **Step 2: Parse GitHub/GitLab push webhook payload**
- [ ] **Step 3: Extract changed files, call ChangeDetector**
- [ ] **Step 4: Enqueue incremental generation task**
- [ ] **Step 5: Run tests**
- [ ] **Step 6: Commit**

---

### Task 6: Graceful Degradation Fallback

**Files:**
- Modify: `wiki/service.py`

- [ ] **Step 1: Wrap generate_incremental in try/except**
- [ ] **Step 2: On failure, log warning and call full generate()**
- [ ] **Step 3: Write test for fallback behavior**
- [ ] **Step 4: Commit**
