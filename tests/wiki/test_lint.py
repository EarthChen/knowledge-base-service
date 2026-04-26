"""Tests for WikiLintService (wiki/lint.py)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from wiki.cache import WikiCache
from wiki.lint import LintIssue, WikiLintService
from wiki.models import PageType, SourceLocation, WikiPage, WikiPageMetadata


def _wrap(rows: list[dict[str, Any]]) -> QueryResultWrapper:
    return QueryResultWrapper(data=rows, raw=[])


class ScriptedStore:
    """Returns canned rows; optional ``script`` overrides per (cypher, params)."""

    def __init__(
        self,
        script: Callable[[str, dict[str, Any]], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.script = script
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
        p = dict(params or {})
        self.calls.append((cypher, p))
        if self.script:
            return _wrap(self.script(cypher, p))
        return _wrap([])


def _minimal_page(
    path: str,
    *,
    title: str = "T",
    content: str = "",
    generated_at: str | None = None,
    source_locations: list[SourceLocation] | None = None,
) -> WikiPage:
    meta = WikiPageMetadata(
        node_count=1,
        edge_count=0,
        generation_mode="structure",
        fallback_tier=None,
        generated_at=generated_at,
    )
    return WikiPage(
        path=path,
        title=title,
        page_type=PageType.CLASS_DETAIL,
        content=content,
        diagrams=[],
        source_locations=source_locations or [],
        metadata=meta,
    )


@pytest.mark.asyncio
async def test_empty_wiki_no_issues() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 0}]
        return []

    svc = WikiLintService(ScriptedStore(script))
    report = await svc.lint("myrepo", scope="all")
    assert report.issues == []
    assert report.stats == {
        "total": 0,
        "errors": 0,
        "warnings": 0,
        "info": 0,
        "confidence_recalibrated": 0,
        "memory_status_updated": 0,
        "memory_tier_updates": 0,
    }


@pytest.mark.asyncio
async def test_staleness_missing_entity_uid_error() -> None:
    def script(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 1}]
        if "stale_uid" in cypher:
            return [{"page_path": "classes/Foo.md", "stale_uid": "uid-missing"}]
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return [
                {
                    "path": "classes/Foo.md",
                    "title": "Foo",
                    "content": "",
                    "generated_at": "",
                    "referenced_entity_uids": ["uid-missing"],
                },
            ]
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return [{"path": "classes/Foo.md", "in_degree": 1}]
        if "semantic_roles" in cypher:
            return []
        return []

    svc = WikiLintService(ScriptedStore(script))
    report = await svc.lint("myrepo", scope="all")
    stale = [i for i in report.issues if i.category == "staleness"]
    assert len(stale) == 1
    assert stale[0].severity == "error"
    assert stale[0].page_path == "classes/Foo.md"
    assert "uid-missing" in stale[0].message


@pytest.mark.asyncio
async def test_orphan_no_incoming_wikilink_warning_excludes_root() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 1}]
        if "stale_uid" in cypher:
            return []
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return [
                {
                    "path": "orphan.md",
                    "title": "Orphan",
                    "content": "x",
                    "generated_at": "",
                    "referenced_entity_uids": [],
                },
                {
                    "path": "index.md",
                    "title": "Index",
                    "content": "",
                    "generated_at": "",
                    "referenced_entity_uids": [],
                },
            ]
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return [{"path": "orphan.md", "in_degree": 0}, {"path": "index.md", "in_degree": 0}]
        if "semantic_roles" in cypher:
            return []
        return []

    svc = WikiLintService(ScriptedStore(script))
    report = await svc.lint("myrepo", scope="all")
    orphans = [i for i in report.issues if i.category == "orphan"]
    paths = {i.page_path for i in orphans}
    assert "orphan.md" in paths
    assert "index.md" not in paths


@pytest.mark.asyncio
async def test_broken_markdown_link_error() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 1}]
        if "stale_uid" in cypher:
            return []
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return [
                {
                    "path": "a.md",
                    "title": "A",
                    "content": "See [x](nonexistent.md)",
                    "generated_at": "",
                    "referenced_entity_uids": [],
                },
                {
                    "path": "ok.md",
                    "title": "Ok",
                    "content": "",
                    "generated_at": "",
                    "referenced_entity_uids": [],
                },
            ]
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return [{"path": "a.md", "in_degree": 1}, {"path": "ok.md", "in_degree": 1}]
        if "semantic_roles" in cypher:
            return []
        return []

    svc = WikiLintService(ScriptedStore(script))
    report = await svc.lint("myrepo", scope="all")
    broken = [i for i in report.issues if i.category == "broken_link"]
    assert len(broken) == 1
    assert broken[0].severity == "error"
    assert "nonexistent.md" in broken[0].message


@pytest.mark.asyncio
async def test_coverage_gap_class_service_role_warning() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 0}]
        if "stale_uid" in cypher:
            return []
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return []
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return []
        if "semantic_roles" in cypher:
            return [{"name": "OrderService", "fqn": "com.example.OrderService"}]
        return []

    svc = WikiLintService(ScriptedStore(script))
    report = await svc.lint("myrepo", scope="all")
    gaps = [i for i in report.issues if i.category == "coverage_gap"]
    assert len(gaps) == 1
    assert gaps[0].severity == "warning"
    assert gaps[0].entity_name == "OrderService"


@pytest.mark.asyncio
async def test_outdated_generated_at_before_last_indexed_info() -> None:
    reg = MagicMock()
    reg.list_all.return_value = [{"repository": "myrepo", "last_indexed": "2025-06-01T12:00:00+00:00"}]

    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 1}]
        if "stale_uid" in cypher:
            return []
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return [
                {
                    "path": "old.md",
                    "title": "Old",
                    "content": "",
                    "generated_at": "2020-01-01T00:00:00+00:00",
                    "referenced_entity_uids": [],
                },
            ]
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return [{"path": "old.md", "in_degree": 1}]
        if "semantic_roles" in cypher:
            return []
        return []

    svc = WikiLintService(ScriptedStore(script), repo_registry=reg)
    report = await svc.lint("myrepo", scope="all")
    outdated = [i for i in report.issues if i.category == "outdated"]
    assert len(outdated) == 1
    assert outdated[0].severity == "info"


@pytest.mark.asyncio
async def test_stats_computation() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 1}]
        if "stale_uid" in cypher:
            return [{"page_path": "a.md", "stale_uid": "gone"}]
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return [
                {
                    "path": "a.md",
                    "title": "A",
                    "content": "[l](missing.md)",
                    "generated_at": "",
                    "referenced_entity_uids": ["gone"],
                },
            ]
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return [{"path": "a.md", "in_degree": 0}]
        if "semantic_roles" in cypher:
            return []
        return []

    svc = WikiLintService(ScriptedStore(script))
    report = await svc.lint("myrepo", scope="all")
    assert report.stats["total"] == len(report.issues)
    assert report.stats["errors"] == sum(1 for i in report.issues if i.severity == "error")
    assert report.stats["warnings"] == sum(1 for i in report.issues if i.severity == "warning")
    assert report.stats["info"] == sum(1 for i in report.issues if i.severity == "info")


@pytest.mark.asyncio
async def test_scope_filtering_module_prefix() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 1}]
        if "stale_uid" in cypher:
            return []
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return [
                {
                    "path": "mod/foo/page.md",
                    "title": "InMod",
                    "content": "[l](bad.md)",
                    "generated_at": "",
                    "referenced_entity_uids": [],
                },
                {
                    "path": "other/x.md",
                    "title": "Other",
                    "content": "[l](nope.md)",
                    "generated_at": "",
                    "referenced_entity_uids": [],
                },
            ]
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return [{"path": "mod/foo/page.md", "in_degree": 1}, {"path": "other/x.md", "in_degree": 1}]
        if "semantic_roles" in cypher:
            return []
        return []

    svc = WikiLintService(ScriptedStore(script))
    report = await svc.lint("myrepo", scope="module:mod/foo")
    broken = [i for i in report.issues if i.category == "broken_link"]
    assert len(broken) == 1
    assert broken[0].page_path == "mod/foo/page.md"


@pytest.mark.asyncio
async def test_cache_used_when_graph_empty() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 0}]
        if "stale_uid" in cypher:
            return []
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return []
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return []
        if "semantic_roles" in cypher:
            return []
        if "n.fqn = $fqn" in cypher:
            return []
        return []

    cache = WikiCache()
    cache.put("r", "repo", "structure", 1, [_minimal_page("c.md", content="[x](y.md)")])
    svc = WikiLintService(ScriptedStore(script), wiki_cache=cache)
    report = await svc.lint("r", scope="all")
    broken = [i for i in report.issues if i.category == "broken_link"]
    assert len(broken) == 1


@pytest.mark.asyncio
async def test_staleness_from_cache_source_locations() -> None:
    def script(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 0}]
        if "stale_uid" in cypher:
            return []
        if "MATCH (wp:WikiPage" in cypher and "generated_at" in cypher:
            return []
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp)" in cypher:
            return []
        if "semantic_roles" in cypher:
            return []
        if "n.fqn = $fqn" in cypher:
            return []
        return []

    loc = SourceLocation(
        file_path="f.java",
        start_line=1,
        end_line=2,
        fqn="com.example.MissingType",
        repository="r",
    )
    cache = WikiCache()
    cache.put("r", "repo", "structure", 1, [_minimal_page("p.md", source_locations=[loc])])
    svc = WikiLintService(ScriptedStore(script), wiki_cache=cache)
    report = await svc.lint("r", scope="all")
    stale = [i for i in report.issues if i.category == "staleness"]
    assert len(stale) >= 1
    assert stale[0].severity == "error"


def test_lint_report_to_dict() -> None:
    from wiki.lint import LintReport

    rep = LintReport(
        issues=[LintIssue(severity="error", category="broken_link", message="m", page_path="a.md")],
        stats={"total": 1, "errors": 1, "warnings": 0, "info": 0},
        checked_at="t",
        scope="all",
    )
    d = rep.to_dict()
    assert d["scope"] == "all"
    assert d["stats"]["errors"] == 1
    assert d["issues"][0]["category"] == "broken_link"
