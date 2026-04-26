"""HTTP tests for GET /api/v1/wiki/pages/{page_uid}/questions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth as auth_module
from api.error_handler import register_exception_handlers
from store.wiki_store import WikiStore


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def app() -> FastAPI:
    from api.routes.wiki_routes import wiki_router

    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(wiki_router)
    return application


def test_suggested_questions_404_when_page_missing(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(app)
    app.state.wiki_store = MagicMock()

    async def _no_page(_self: WikiStore, _page_uid: str) -> None:
        return None

    monkeypatch.setattr(WikiStore, "get_suggested_questions_context", _no_page)
    r = client.get("/api/v1/wiki/pages/WikiPage%3Ademo%3A1/questions")
    assert r.status_code == 404


def test_suggested_questions_returns_questions_and_page_uid(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(app)
    app.state.wiki_store = MagicMock()

    async def _ctx(_self: WikiStore, page_uid: str) -> dict:
        return {
            "page_uid": page_uid,
            "entity_name": "UserService",
            "domain": "用户域",
            "callers": ["A", "B", "C"],
            "callees": ["RedisClient"],
            "cross_domain_callers": ["A"],
        }

    monkeypatch.setattr(WikiStore, "get_suggested_questions_context", _ctx)
    r = client.get("/api/v1/wiki/pages/WikiPage%3Ademo%3A1/questions")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["page_uid"] == "WikiPage:demo:1"
    assert "questions" in data
    assert isinstance(data["questions"], list)
    assert len(data["questions"]) >= 1
