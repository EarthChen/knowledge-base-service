"""HTTP tests for wiki page review and regeneration endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import WikiTaskRegistry, get_task_registry_dep, get_wiki_service_dep, wiki_router


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _review_app(mock_wiki: Any) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.wiki_tasks = WikiTaskRegistry()

    async def override_wiki() -> Any:
        return mock_wiki

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_task_registry_dep] = override_registry
    return TestClient(app)


def test_set_page_review_status() -> None:
    mock_svc = MagicMock()
    mock_svc.set_page_review_status = AsyncMock(return_value={"status": "ok"})
    client = _review_app(mock_svc)
    resp = client.post(
        "/api/v1/wiki/pages/wiki%2Fpayment/review",
        json={"status": "approved", "notes": "Looks good"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    mock_svc.set_page_review_status.assert_awaited_once_with(
        "wiki/payment", "approved", "Looks good",
    )


def test_batch_review() -> None:
    mock_svc = MagicMock()
    mock_svc.batch_review = AsyncMock(return_value={"updated": 2})
    client = _review_app(mock_svc)
    resp = client.post(
        "/api/v1/wiki/review/batch",
        json={
            "business_id": "test-biz",
            "reviews": [
                {"page_path": "wiki/payment", "status": "approved"},
                {"page_path": "wiki/user", "status": "needs_revision", "notes": "Add flow"},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}
    mock_svc.batch_review.assert_awaited_once_with(
        "test-biz",
        [
            {"page_path": "wiki/payment", "status": "approved", "notes": ""},
            {"page_path": "wiki/user", "status": "needs_revision", "notes": "Add flow"},
        ],
    )


def test_trigger_regeneration() -> None:
    mock_svc = MagicMock()
    mock_svc.trigger_page_regeneration = AsyncMock(return_value={"task_id": "regen-123"})
    client = _review_app(mock_svc)
    resp = client.post(
        "/api/v1/wiki/pages/wiki%2Fpayment/regenerate",
        json={"heal_hints": "Add refund flow details"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"task_id": "regen-123"}
    mock_svc.trigger_page_regeneration.assert_awaited_once_with(
        "wiki/payment", "Add refund flow details",
    )


def test_set_page_review_fallback_when_method_missing() -> None:
    client = _review_app(object())
    resp = client.post(
        "/api/v1/wiki/pages/wiki%2Fpayment/review",
        json={"status": "pending_review", "notes": ""},
    )
    assert resp.status_code == 501
