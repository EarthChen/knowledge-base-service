"""WikiLintService schema validation when ``schema_validation_enabled`` is set."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.lint import WikiLintService


@pytest.mark.asyncio
async def test_lint_schema_flags_entity_page_violations() -> None:
    page = {
        "uid": "WikiPage:r1:Class.md",
        "path": "Class.md",
        "title": "bad",
        "content": "# x\n",
        "page_type": "entity",
        "generated_at": "2026-04-26T00:00:00+00:00",
        "referenced_entity_uids": [],
        "stability_factor": None,
        "last_accessed": "",
    }
    store = MagicMock()
    wiki_store = MagicMock()
    wiki_store.list_wiki_pages_for_repo = AsyncMock(
        return_value=MagicMock(data=[page]),
    )
    cfg = SimpleNamespace(
        schema_validation_enabled=True,
        schema_path="wiki/schema.yaml",
    )
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
        "_check_forgetting",
    ):
        setattr(svc, name, AsyncMock(return_value=[]))

    report = await svc.lint("r1", scope="all")
    sch = [i for i in report.issues if i.category == "schema"]
    assert sch
    assert all(i.severity == "error" for i in sch)
    assert report.stats.get("errors", 0) >= 1


@pytest.mark.asyncio
async def test_lint_schema_skips_when_flag_off() -> None:
    store = MagicMock()
    wiki_store = MagicMock()
    wiki_store.list_wiki_pages_for_repo = AsyncMock(
        return_value=MagicMock(data=[]),
    )
    cfg = SimpleNamespace(schema_validation_enabled=False)
    svc = WikiLintService(store, wiki_store=wiki_store, wiki_config=cfg)
    for name in (
        "_check_staleness",
        "_check_orphans",
        "_check_broken_links",
        "_check_coverage_gaps",
        "_check_outdated_content",
        "_check_contradictions",
        "_check_forgetting",
    ):
        setattr(svc, name, AsyncMock(return_value=[]))
    report = await svc.lint("r1", scope="all")
    assert not any(i.category == "schema" for i in report.issues)
