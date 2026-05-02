"""Tests for POST /api/v1/wiki/{repository}/export/preview and .../execute."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import WikiTaskRegistry, get_task_registry_dep, get_wiki_cache_dep, get_wiki_service_dep, wiki_router
from wiki.cache import WikiCache
from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.service import WikiRepoNotFoundError


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _page(path: str, content: str = "C") -> WikiPage:
    return WikiPage(
        path=path,
        title="T",
        page_type=PageType.MODULE_OVERVIEW,
        content=content,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=1, edge_count=0),
    )


@pytest.fixture
def export_client(tmp_path: Path) -> tuple[TestClient, WikiCache, Path]:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.wiki_tasks = WikiTaskRegistry()
    cache = WikiCache()
    cache.put("myrepo", "repo", "structure", 1, [_page("api.md", "API body")])

    mock_wiki = MagicMock()
    mock_wiki.ensure_repository = AsyncMock(return_value=None)

    async def override_wiki() -> MagicMock:
        return mock_wiki

    def override_cache() -> WikiCache:
        return cache

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_wiki_cache_dep] = override_cache
    app.dependency_overrides[get_task_registry_dep] = override_registry

    td = tmp_path / "wiki_out"
    td.mkdir()
    return TestClient(app), cache, td


def test_post_wiki_export_preview_returns_200(export_client: tuple[TestClient, WikiCache, Path]) -> None:
    client, _cache, td = export_client
    r = client.post(
        "/api/v1/wiki/myrepo/export/preview",
        json={"target_dir": str(td)},
    )
    assert r.status_code == 200
    body = r.json()
    assert "diffs" in body
    assert "total_files" in body
    assert "created" in body
    assert "updated" in body
    assert "skipped" in body
    assert body["total_files"] == 1
    assert len(body["diffs"]) == 1
    assert body["diffs"][0]["file_path"] == "api.md"
    assert body["diffs"][0]["action"] == "create"


def test_post_wiki_export_execute_returns_200(export_client: tuple[TestClient, WikiCache, Path]) -> None:
    client, _cache, td = export_client
    r = client.post(
        "/api/v1/wiki/myrepo/export/execute",
        json={"target_dir": str(td), "selected_files": ["api.md"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("created", 0) >= 0
    assert (td / "api.md").exists()


def test_export_preview_repo_not_found(tmp_path: Path) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.wiki_tasks = WikiTaskRegistry()
    mock_wiki = MagicMock()
    mock_wiki.ensure_repository = AsyncMock(side_effect=WikiRepoNotFoundError("missing"))

    async def override_wiki() -> MagicMock:
        return mock_wiki

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_wiki_cache_dep] = lambda: WikiCache()
    app.dependency_overrides[get_task_registry_dep] = lambda: app.state.wiki_tasks

    client = TestClient(app)
    r = client.post("/api/v1/wiki/missing/export/preview", json={"target_dir": str(tmp_path / "x")})
    assert r.status_code == 404
