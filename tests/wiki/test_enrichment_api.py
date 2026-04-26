"""Tests for wiki enrichment status and manual trigger endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from api.routes.wiki_routes import (
    WikiTaskRegistry,
    get_task_registry_dep,
    get_wiki_service_dep,
    wiki_router,
)


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.state.wiki_tasks = WikiTaskRegistry()

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.include_router(wiki_router)
    app.dependency_overrides[get_task_registry_dep] = override_registry
    return app


def test_enrichment_status_endpoint(app: FastAPI) -> None:
    """GET enrichment-status should return distribution."""
    client = TestClient(app)
    mock_svc = MagicMock()
    mock_svc.get_enrichment_status = AsyncMock(
        return_value={
            "repository": "test-repo",
            "total_pages": 10,
            "base": 3,
            "enriched": 5,
            "encyclopedia": 2,
        },
    )

    async def override_wiki() -> MagicMock:
        return mock_svc

    app.dependency_overrides[get_wiki_service_dep] = override_wiki

    r = client.get("/api/v1/wiki/test-repo/enrichment-status")
    assert r.status_code == 200
    data = r.json()
    assert data["total_pages"] == 10
    mock_svc.get_enrichment_status.assert_awaited_once()


def test_enrich_trigger_endpoint(app: FastAPI) -> None:
    """POST enrich should return 202."""
    client = TestClient(app)
    mock_svc = MagicMock()
    mock_svc.trigger_enrichment = AsyncMock(
        return_value={
            "eligible_pages": 5,
            "repository": "test-repo",
            "note": "Enrichment runs automatically during wiki generation.",
        },
    )

    async def override_wiki() -> MagicMock:
        return mock_svc

    app.dependency_overrides[get_wiki_service_dep] = override_wiki

    r = client.post("/api/v1/wiki/test-repo/enrich")
    assert r.status_code == 202
    assert r.json()["eligible_pages"] == 5
    mock_svc.trigger_enrichment.assert_awaited_once()
