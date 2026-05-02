"""Tests for POST /api/v1/wiki/ask/crystallize."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import wiki_router
from api.routes.wiki_shared import get_wiki_ask_dep
from wiki.ask import WikiAskService


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def test_crystallize_returns_200() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    ask = MagicMock(spec=WikiAskService)
    ask.crystallize = AsyncMock(
        return_value={
            "page_uid": "WikiPage:r:crystallized/t-abc.md",
            "title": "Hi",
            "path": "crystallized/t-abc.md",
        },
    )

    async def _ask_dep() -> MagicMock:
        return ask

    app.dependency_overrides[get_wiki_ask_dep] = _ask_dep
    app.include_router(wiki_router)
    c = TestClient(app)
    r = c.post(
        "/api/v1/wiki/ask/crystallize",
        json={
            "repository": "r",
            "question": "Q?",
            "answer": "A.",
            "sources": ["a.md"],
            "conversation_id": "cid-1",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "crystallized/t-abc.md"
    assert data["title"] == "Hi"
    assert data["conversation_id"] == "cid-1"
    ask.crystallize.assert_awaited_once()
