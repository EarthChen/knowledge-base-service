# tests/wiki/test_export_api.py
"""Unit tests for business wiki export API endpoint."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import wiki_router
from store.falkordb_store import QueryResultWrapper


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with the wiki router."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    return app


def _mock_app_state(app: FastAPI, wiki_store: Any = None) -> None:
    """Attach mock wiki_store to app.state."""
    app.state.wiki_store = wiki_store


def _graph_store(tree_rows: list[dict[str, Any]], page_rows: list[dict[str, Any]]) -> AsyncMock:
    """Mock FalkorDB-style store: WikiStore delegates to execute_query."""

    store = AsyncMock()

    async def execute_query(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
        if "(wp:WikiPage)" in cypher:
            return QueryResultWrapper(page_rows)
        if "OPTIONAL MATCH path = (ws)-[:HAS_CHILD" in cypher:
            # QueryResultWrapper is falsy when raw is empty; production rows set raw.
            raw = [[1]] * len(tree_rows) if tree_rows else []
            return QueryResultWrapper(tree_rows, raw=raw)
        return QueryResultWrapper([])

    store.execute_query = AsyncMock(side_effect=execute_query)
    return store


@pytest.fixture
def mock_store() -> AsyncMock:
    return _graph_store([], [])


@pytest.fixture
def mock_store_with_data() -> AsyncMock:
    tree = [
        {
            "uid": "s1",
            "title": "Domain",
            "label": "WikiSection",
            "depth": 1,
            "sort_order": 0,
            "path": "",
            "page_type": "",
        },
    ]
    pages = [
        {
            "uid": "wp1",
            "title": "Page",
            "path": "/Domain/Page",
            "content": "# Page content\nSee [[/Domain/Other]].",
            "page_type": "entity",
            "repository": "repo",
            "importance_tier": "core",
            "content_hash": "h1",
        },
    ]
    return _graph_store(tree, pages)


class TestExportEndpointValidation:
    def test_invalid_format_returns_422(self) -> None:
        app = _make_app()
        _mock_app_state(app)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "invalid_format"},
        )
        assert r.status_code == 422

    def test_invalid_view_type_returns_422(self) -> None:
        app = _make_app()
        _mock_app_state(app)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "markdown", "view_type": "bad"},
        )
        assert r.status_code == 422

    def test_invalid_min_tier_returns_422(self) -> None:
        app = _make_app()
        _mock_app_state(app)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "markdown", "min_tier": "ultra"},
        )
        assert r.status_code == 422


class TestExportEndpointMarkdown:
    def test_markdown_returns_file_list(self, mock_store_with_data: AsyncMock) -> None:
        app = _make_app()
        _mock_app_state(app, wiki_store=mock_store_with_data)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "markdown"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "markdown"
        assert data["business_id"] == "test"
        assert "files" in data
        assert data["total_files"] > 0

    def test_empty_tree_returns_empty(self, mock_store: AsyncMock) -> None:
        app = _make_app()
        _mock_app_state(app, wiki_store=mock_store)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "empty", "format": "markdown"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total_files"] == 0


class TestExportEndpointZip:
    def test_zip_returns_binary(self, mock_store_with_data: AsyncMock) -> None:
        app = _make_app()
        _mock_app_state(app, wiki_store=mock_store_with_data)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "zip"},
        )
        assert r.status_code == 200
        assert "application/zip" in r.headers.get("content-type", "")
        buf = io.BytesIO(r.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert len(names) > 0
            assert any("README.md" in n for n in names)


class TestExportEndpointGit:
    def test_git_format_requires_git_config(self, mock_store: AsyncMock) -> None:
        app = _make_app()
        _mock_app_state(app, wiki_store=mock_store)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "git"},
        )
        assert r.status_code == 400
        data = r.json()
        assert "git_config" in json.dumps(data).lower()


class TestExportEndpointObsidian:
    def test_obsidian_returns_with_config(self, mock_store_with_data: AsyncMock) -> None:
        app = _make_app()
        _mock_app_state(app, wiki_store=mock_store_with_data)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "obsidian"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "obsidian"
        paths = [f["path"] for f in data.get("files", [])]
        assert any(".obsidian" in p for p in paths)


class TestExportEndpointMkDocs:
    def test_mkdocs_returns_with_yml(self, mock_store_with_data: AsyncMock) -> None:
        app = _make_app()
        _mock_app_state(app, wiki_store=mock_store_with_data)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/wiki/export",
            json={"business_id": "test", "format": "mkdocs"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["format"] == "mkdocs"
        paths = [f["path"] for f in data.get("files", [])]
        assert "mkdocs.yml" in paths
