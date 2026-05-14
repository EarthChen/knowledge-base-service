"""HTTP tests for wiki edit session REST routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    from api.routes.wiki_edit_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/wiki")

    mock_svc = AsyncMock()
    mock_svc.create_session = AsyncMock(return_value="sess-abc123")
    mock_svc.get_session = AsyncMock(return_value=None)
    mock_svc.delete_session = AsyncMock()
    mock_svc.apply_edit = AsyncMock(
        return_value={
            "page_uid": "p1",
            "content": "# New",
            "original_content": "# Old",
        },
    )

    app.state.wiki_edit_service = mock_svc

    queue_mock = MagicMock()
    mock_svc.send_message = AsyncMock(return_value=queue_mock)

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_create_edit_session(client):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session",
        json={"prompt": "Fix the description", "current_content": "# Page\n\nOld text"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data


def test_create_edit_session_missing_prompt(client):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session",
        json={"current_content": "# Page"},
    )
    assert resp.status_code == 422


def test_create_edit_session_empty_prompt(client):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session",
        json={"prompt": "", "current_content": "# Page"},
    )
    assert resp.status_code == 422


def test_delete_edit_session(client):
    resp = client.delete("/api/v1/wiki/pages/page-1/edit-session/sess-abc123")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_apply_edit(client):
    resp = client.post("/api/v1/wiki/pages/page-1/edit-session/sess-abc123/apply")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page_uid"] == "p1"
    assert data["content"] == "# New"


def test_send_message(client):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session/sess-abc123/message",
        json={"prompt": "More detail please"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"
