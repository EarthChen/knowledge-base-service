"""HTTP tests for GET /api/v1/graph/insights/{repository}."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from main import _get_service, viewer_router
from store.falkordb_store import QueryResultWrapper


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_client(mock_svc: MagicMock) -> TestClient:
    app = FastAPI()
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

    def test_missing_graph_store_returns_503(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()
        mock_svc.store.graph = None

        client = _make_client(mock_svc)
        r = client.get("/api/v1/graph/insights/my-repo")
        assert r.status_code == 503
        assert "graph" in r.json()["detail"].lower() or "store" in r.json()["detail"].lower()
