"""HTTP tests for POST /api/v1/wiki/search — P1.5."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from api.routes.wiki_routes import (
    WikiTaskRegistry,
    get_task_registry_dep,
    get_wiki_search_dep,
    get_wiki_service_dep,
    wiki_router,
)
from wiki.search import SearchResponse, SearchResult


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_search_app(mock_search: Any | None = None) -> tuple[FastAPI, TestClient, Any]:
    app = FastAPI()
    app.state.wiki_tasks = WikiTaskRegistry()

    svc = mock_search if mock_search is not None else MagicMock()

    async def override_wiki() -> Any:
        return MagicMock()

    async def override_search() -> Any:
        return svc

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_wiki_search_dep] = override_search

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.dependency_overrides[get_task_registry_dep] = override_registry

    return app, TestClient(app), svc


class TestWikiSearch:
    def test_search_valid_query(self) -> None:
        resp = SearchResponse(
            results=[
                SearchResult(
                    page_path="classes/UserService.md",
                    title="UserService",
                    score=0.92,
                    snippet="UserService delegates...",
                    source_locations=[{"file_path": "src/User.java", "start_line": 1}],
                    context={"repository": "my-repo"},
                )
            ],
            query_expansion={"original": "authentication login", "expanded_queries": ["x"], "terms": []},
            total=1,
        )
        mock_search = MagicMock()
        mock_search.search = AsyncMock(return_value=resp)
        _, client, _ = _make_search_app(mock_search)

        r = client.post(
            "/api/v1/wiki/search",
            json={
                "repository": "my-repo",
                "query": "authentication login",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["results"]) == 1
        assert body["results"][0]["page_path"] == "classes/UserService.md"
        assert body["results"][0]["title"] == "UserService"
        mock_search.search.assert_awaited_once()
        assert mock_search.search.await_args.kwargs["repository"] == "my-repo"

    def test_search_empty_query_400(self) -> None:
        _, client, mock_search = _make_search_app(MagicMock())
        r = client.post(
            "/api/v1/wiki/search",
            json={
                "repository": "my-repo",
                "query": "",
            },
        )
        assert r.status_code == 422
        mock_search.search.assert_not_called()

    def test_search_mode_keyword(self) -> None:
        mock_search = MagicMock()
        mock_search.search = AsyncMock(
            return_value=SearchResponse(results=[], query_expansion={}, total=0)
        )
        _, client, _ = _make_search_app(mock_search)

        r = client.post(
            "/api/v1/wiki/search",
            json={
                "repository": "my-repo",
                "query": "hello",
                "mode": "keyword",
            },
        )
        assert r.status_code == 200
        mock_search.search.assert_awaited_once()
        assert mock_search.search.await_args.kwargs.get("mode") == "keyword"

    def test_search_limit_applied(self) -> None:
        mock_search = MagicMock()
        mock_search.search = AsyncMock(
            return_value=SearchResponse(results=[], query_expansion={}, total=0)
        )
        _, client, _ = _make_search_app(mock_search)

        r = client.post(
            "/api/v1/wiki/search",
            json={
                "repository": "my-repo",
                "query": "hello",
                "limit": 3,
            },
        )
        assert r.status_code == 200
        assert mock_search.search.await_args.kwargs.get("limit") == 3

    def test_search_service_unavailable(self) -> None:
        app = FastAPI()
        app.state.wiki_tasks = WikiTaskRegistry()

        async def override_wiki() -> Any:
            return MagicMock()

        app.include_router(wiki_router)
        app.dependency_overrides[get_wiki_service_dep] = override_wiki

        def override_registry() -> WikiTaskRegistry:
            return app.state.wiki_tasks

        app.dependency_overrides[get_task_registry_dep] = override_registry
        # wiki_search_service intentionally unset

        client = TestClient(app)
        r = client.post(
            "/api/v1/wiki/search",
            json={"repository": "my-repo", "query": "x"},
        )
        assert r.status_code == 503
        detail = r.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("error") == "service_unavailable"
