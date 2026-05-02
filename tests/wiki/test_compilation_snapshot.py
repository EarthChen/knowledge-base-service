from __future__ import annotations

import pytest

from core.config import Settings
from wiki.compilation_snapshot import WikiCompilationSnapshot


class _Result:
    def __init__(self, data: list[dict] | list) -> None:
        self.data = data


class _FakeGraph:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.queries: list[tuple[str, dict]] = []

    async def execute_query(self, cypher: str, params: dict | None = None):
        self.queries.append((cypher, params or {}))
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_generate_single_file_below_threshold():
    rows = [
        {
            "path": "modules/auth.md",
            "title": "Auth",
            "summary": "OAuth2 and JWT " + ("x" * 300),
            "content_excerpt": "OAuth2 and JWT " + ("x" * 300),
            "page_type": "module_overview",
            "importance_tier": "core",
            "confidence": 0.85,
            "wikilinks": ["user-model"],
        }
    ]
    g = _FakeGraph(rows)
    cfg = Settings().wiki
    snap = WikiCompilationSnapshot(graph=g, wiki_config=cfg)
    out = await snap.generate("acme", "my-repo")
    assert "# Knowledge Base Snapshot" in out
    assert "my-repo" in out
    assert "Auth" in out
    assert "0.85" in out


@pytest.mark.asyncio
async def test_layered_output_over_threshold():
    many = [
        {
            "path": f"modules/p{i}.md",
            "title": f"Page{i}",
            "summary": "S",
            "content_excerpt": "S",
            "page_type": "module_overview",
            "importance_tier": "standard",
            "confidence": 0.5,
            "wikilinks": [],
        }
        for i in range(101)
    ]
    g = _FakeGraph(many)
    cfg = Settings().wiki
    snap = WikiCompilationSnapshot(graph=g, wiki_config=cfg)
    layered = await snap.generate_layered("acme", "my-repo")
    assert "index" in layered
    assert "modules" in layered
    assert len(layered["modules"]) >= 1


@pytest.mark.asyncio
async def test_empty_repo():
    g = _FakeGraph([])
    cfg = Settings().wiki
    snap = WikiCompilationSnapshot(graph=g, wiki_config=cfg)
    out = await snap.generate("acme", "empty-repo")
    assert "empty-repo" in out
    assert "Pages: 0" in out


@pytest.mark.asyncio
async def test_generate_and_persist_single():
    rows = [
        {
            "path": "core/main.md",
            "title": "Main",
            "content_excerpt": "Entry point",
            "page_type": "module_overview",
            "importance_tier": "core",
            "confidence": 0.9,
            "wikilinks": [],
        }
    ]
    g = _FakeGraph(rows)
    cfg = Settings().wiki
    snap = WikiCompilationSnapshot(graph=g, wiki_config=cfg)
    persisted = {}

    async def fake_persist(data, repo, layered):
        persisted["data"] = data
        persisted["repo"] = repo
        persisted["layered"] = layered

    result = await snap.generate_and_persist("b", "repo1", persist_fn=fake_persist)
    assert "Main" in result
    assert persisted["repo"] == "repo1"
    assert persisted["layered"] is False
