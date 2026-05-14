"""HTTP tests for GET /api/v1/graph/insights/{repository}."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from main import _get_service, viewer_router
from store.analysis_store import _Q_RESOLVE_REPOS
from store.falkordb_store import QueryResultWrapper


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_client(mock_svc: MagicMock) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(viewer_router)

    async def override_get_service():
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service
    return TestClient(app)


def _stats_row() -> dict:
    return {
        "class_count": 1,
        "module_count": 1,
        "calls_same_repo": 0,
        "imports_same_repo": 0,
    }


class TestGraphInsightsApi:
    def test_get_graph_insights_returns_200_with_insights_report(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()
        mock_svc.store.graph = MagicMock()

        async def router(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                assert (params or {}).get("repos") == ["my-repo"]
                return QueryResultWrapper(data=[_stats_row()], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.get("/api/v1/graph/insights/my-repo")
        assert r.status_code == 200
        body = r.json()
        assert "insights" in body
        assert "graph_stats" in body
        assert "analyzed_at" in body
        assert body["graph_stats"]["class_count"] == 1
        assert isinstance(body["insights"], list)

    def test_business_id_resolves_wiki_repos_and_aggregates_stats(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()
        mock_svc.store.graph = MagicMock()

        async def router(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            p = params or {}
            if _Q_RESOLVE_REPOS in cypher:
                assert p.get("business_id") == "acme-biz"
                return QueryResultWrapper(data=[{"repos": ["indexed-code-repo"]}], raw=[])
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                assert p.get("repos") == ["indexed-code-repo"]
                return QueryResultWrapper(data=[_stats_row()], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.get("/api/v1/graph/insights/acme-biz", params={"business_id": "acme-biz"})
        assert r.status_code == 200
        body = r.json()
        assert body["graph_stats"]["class_count"] == 1

    def test_business_id_no_wiki_space_returns_empty_stats(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()
        mock_svc.store.graph = MagicMock()

        async def router(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            if _Q_RESOLVE_REPOS in cypher:
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.get(
            "/api/v1/graph/insights/unknown-biz",
            params={"business_id": "missing-wiki"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["graph_stats"]["class_count"] == 0
        assert body["graph_stats"]["module_count"] == 0
        assert body["insights"] == []

    def test_missing_graph_store_returns_503(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()
        mock_svc.store.graph = None

        client = _make_client(mock_svc)
        r = client.get("/api/v1/graph/insights/my-repo")
        assert r.status_code == 503
        msg = (r.json().get("error") or {}).get("message", "").lower()
        assert "graph" in msg or "store" in msg
