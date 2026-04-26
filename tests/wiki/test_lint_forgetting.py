"""WikiLintService forgetting (memory_status) when ``forgetting_enabled`` is set."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import NodeLabel
from wiki.lint import WikiLintService


@pytest.mark.asyncio
async def test_lint_forgetting_sets_archived_on_stale_page() -> None:
    page = {
        "uid": "WikiPage:r1:src/A.md",
        "path": "src/A.md",
        "title": "A",
        "content": "# A",
        "page_type": "class",
        "generated_at": "2020-01-01T00:00:00+00:00",
        "referenced_entity_uids": [],
        "stability_factor": 7.0,
        "last_accessed": "",
    }

    store = MagicMock()
    store.execute_query = AsyncMock()
    wiki_store = MagicMock()
    wiki_store.list_wiki_pages_for_repo = AsyncMock(
        return_value=MagicMock(data=[page]),
    )
    up = AsyncMock()
    wiki_store.update_node_property = up

    cfg = SimpleNamespace(forgetting_enabled=True, forgetting_initial_stability=7.0)
    svc = WikiLintService(
        store,
        wiki_store=wiki_store,
        wiki_config=cfg,
    )
    for name in (
        "_check_staleness",
        "_check_orphans",
        "_check_broken_links",
        "_check_coverage_gaps",
        "_check_outdated_content",
        "_check_contradictions",
        "_check_schema",
    ):
        setattr(svc, name, AsyncMock(return_value=[]))

    report = await svc.lint("r1", scope="all")

    up.assert_awaited()
    call = up.await_args
    assert call[0][0] == NodeLabel.WIKI_PAGE
    assert call[0][2] == "memory_status"
    assert call[0][3] == "archived"
    assert report.stats.get("memory_status_updated") == 1
    assert any(i.category == "memory_retention" for i in report.issues)
    mem_issues = [i for i in report.issues if i.category == "memory_retention"]
    assert mem_issues[0].severity == "warning"


@pytest.mark.asyncio
async def test_lint_forgetting_skips_when_flag_off() -> None:
    store = MagicMock()
    wiki_store = MagicMock()
    wiki_store.list_wiki_pages_for_repo = AsyncMock(
        return_value=MagicMock(data=[]),
    )
    up = AsyncMock()
    wiki_store.update_node_property = up
    cfg = SimpleNamespace(forgetting_enabled=False, forgetting_initial_stability=7.0)
    svc = WikiLintService(
        store,
        wiki_store=wiki_store,
        wiki_config=cfg,
    )
    for name in (
        "_check_staleness",
        "_check_orphans",
        "_check_broken_links",
        "_check_coverage_gaps",
        "_check_outdated_content",
        "_check_contradictions",
        "_check_schema",
    ):
        setattr(svc, name, AsyncMock(return_value=[]))
    report = await svc.lint("r1", scope="all")
    up.assert_not_awaited()
    assert report.stats.get("memory_status_updated") == 0
