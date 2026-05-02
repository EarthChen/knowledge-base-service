"""Tests for FalkorDB downstream fields on GET /api/v1/health."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.routes.kb_routers import public_router


@pytest.fixture
def health_only_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(public_router)
    return app


def test_health_ok_includes_falkordb_ready(
    monkeypatch: pytest.MonkeyPatch,
    health_only_app: FastAPI,
) -> None:
    import api.kb_state as kb_state

    reg = MagicMock()
    reg.readiness = AsyncMock(
        return_value=(
            {
                "status": "ok",
                "redis": "ready",
                "embedding": "ready",
                "auth_mode": "open",
                "wiki": {"reasoning_effort": "auto"},
            },
            200,
        )
    )
    reg.falkordb_graph_ping = AsyncMock(return_value="ready")
    monkeypatch.setattr(kb_state, "registry", reg)

    client = TestClient(health_only_app)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["components"]["falkordb"] == "ready"


def test_health_degraded_when_falkordb_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    health_only_app: FastAPI,
) -> None:
    import api.kb_state as kb_state

    reg = MagicMock()
    reg.readiness = AsyncMock(
        return_value=(
            {
                "status": "ok",
                "redis": "ready",
                "embedding": "ready",
                "auth_mode": "open",
                "wiki": {"reasoning_effort": "auto"},
            },
            200,
        )
    )
    reg.falkordb_graph_ping = AsyncMock(return_value="unreachable")
    monkeypatch.setattr(kb_state, "registry", reg)

    client = TestClient(health_only_app)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "degraded"
    assert data["falkordb"] == "unreachable"
    assert data["components"]["falkordb"] == "unreachable"


def test_health_passes_through_non_200_from_readiness(
    monkeypatch: pytest.MonkeyPatch,
    health_only_app: FastAPI,
) -> None:
    import api.kb_state as kb_state

    reg = MagicMock()
    reg.readiness = AsyncMock(return_value=({"status": "initializing", "embedding": "not_loaded"}, 503))
    reg.falkordb_graph_ping = AsyncMock()
    monkeypatch.setattr(kb_state, "registry", reg)

    client = TestClient(health_only_app)
    r = client.get("/api/v1/health")
    assert r.status_code == 503
    assert r.json()["status"] == "initializing"
    reg.falkordb_graph_ping.assert_not_called()
