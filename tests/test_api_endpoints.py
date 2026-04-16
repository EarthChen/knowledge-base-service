"""HTTP tests for selected viewer API routes (mocked KnowledgeBaseService)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from main import _get_service, viewer_router
from store.falkordb_store import QueryResultWrapper


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Viewer routes use require_role; when the token registry is empty, resolve_token allows access."""
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_architecture_client() -> tuple[TestClient, MagicMock]:
    """Minimal app with viewer routes only; graph store fully mocked."""
    mock_svc = MagicMock()
    # Endpoint calls count_classes_by_architecture_layer then search_classes_by_architecture_layer.
    mock_svc.store.execute_query = AsyncMock(
        side_effect=[
            QueryResultWrapper([{"cnt": 2}]),
            QueryResultWrapper([]),
        ]
    )

    app = FastAPI()
    app.include_router(viewer_router)

    async def override_get_service():
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service
    return TestClient(app), mock_svc


class TestArchitectureSearchEndpoint:
    def test_architecture_search_basic(self) -> None:
        client, _mock_svc = _make_architecture_client()
        r = client.get("/api/v1/search/architecture", params={"layer": "business"})
        assert r.status_code == 200
        body = r.json()
        assert body["layer"] == "business"
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert body["search"] is None
        assert body["total_count"] == 2
        assert body["classes"] == []

    def test_architecture_search_with_pagination(self) -> None:
        client, _mock_svc = _make_architecture_client()
        r = client.get(
            "/api/v1/search/architecture",
            params={"layer": "model", "offset": 10, "limit": 3},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 3
        assert body["offset"] == 10

    def test_architecture_search_with_name_filter(self) -> None:
        client, _mock_svc = _make_architecture_client()
        r = client.get(
            "/api/v1/search/architecture",
            params={"layer": "data_access", "search": " Order "},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["search"] == "Order"

    def test_architecture_search_invalid_layer(self) -> None:
        client, _mock_svc = _make_architecture_client()
        r = client.get(
            "/api/v1/search/architecture",
            params={"layer": "not_a_real_layer"},
        )
        assert r.status_code == 422
        assert "Invalid layer" in r.json()["detail"]
