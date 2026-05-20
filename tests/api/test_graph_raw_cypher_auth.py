"""HTTP auth for POST /api/v1/graph raw_cypher queries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth
from api.error_handler import register_exception_handlers
from api.routes.search_routes import viewer_router
from core.auth import Role, TokenInfo
from main import _get_service


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    import core.config as config_module

    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def _make_client(mock_handler: MagicMock) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(viewer_router)

    mock_svc = MagicMock()
    mock_svc.mcp_handler = mock_handler

    async def override_get_service():
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service
    return TestClient(app)


class TestGraphRawCypherAuth:
    def test_raw_cypher_forbidden_for_viewer_when_tokens_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            auth,
            "_token_registry",
            {
                "viewer-tok": TokenInfo(role=Role.VIEWER),
                "admin-tok": TokenInfo(role=Role.ADMIN),
            },
        )
        handler = MagicMock()
        handler.handle_rag_graph = AsyncMock(return_value={"type": "raw_cypher", "results": []})
        client = _make_client(handler)

        r = client.post(
            "/api/v1/graph",
            json={"query_type": "raw_cypher", "cypher": "MATCH (n) RETURN n"},
            headers={"Authorization": "Bearer viewer-tok"},
        )

        assert r.status_code == 403
        handler.handle_rag_graph.assert_not_called()

    def test_raw_cypher_ok_for_admin_when_tokens_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            auth,
            "_token_registry",
            {"admin-tok": TokenInfo(role=Role.ADMIN)},
        )
        handler = MagicMock()
        handler.handle_rag_graph = AsyncMock(return_value={"type": "raw_cypher", "results": []})
        client = _make_client(handler)

        r = client.post(
            "/api/v1/graph",
            json={"query_type": "raw_cypher", "cypher": "MATCH (n) RETURN n LIMIT 1"},
            headers={"Authorization": "Bearer admin-tok"},
        )

        assert r.status_code == 200
        handler.handle_rag_graph.assert_called_once()

    def test_raw_cypher_401_without_auth_when_tokens_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            auth,
            "_token_registry",
            {"admin-tok": TokenInfo(role=Role.ADMIN)},
        )
        handler = MagicMock()
        handler.handle_rag_graph = AsyncMock()
        client = _make_client(handler)

        r = client.post(
            "/api/v1/graph",
            json={"query_type": "raw_cypher", "cypher": "MATCH (n) RETURN n"},
        )

        assert r.status_code == 401
        handler.handle_rag_graph.assert_not_called()
