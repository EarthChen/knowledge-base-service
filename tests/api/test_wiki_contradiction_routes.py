"""Tests for /api/v1/wiki/contradictions routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import wiki_router
from core.config import get_settings


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def test_list_contradictions_empty_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import api.routes.wiki_contradiction_routes as wcr

    w = get_settings()
    assert w is not None
    monkeypatch.setattr(
        wcr,
        "get_settings",
        lambda: SimpleNamespace(
            wiki=SimpleNamespace(
                **{**w.wiki.model_dump(), "contradiction_detection_enabled": False},
            ),
        ),
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(wiki_router)
    c = TestClient(app)
    r = c.get("/api/v1/wiki/contradictions", params={"page_uid": "u1"})
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_list_contradictions_with_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    w = get_settings()
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "uid": "c1",
                    "page_uid_a": "a",
                    "page_uid_b": "b",
                    "status": "detected",
                },
            ],
        ),
    )
    app = FastAPI()
    app.state.wiki_store = store
    register_exception_handlers(app)
    app.include_router(wiki_router)

    import api.routes.wiki_contradiction_routes as wcr

    full = w.wiki.model_dump()
    full["contradiction_detection_enabled"] = True
    monkeypatch.setattr(
        wcr,
        "get_settings",
        lambda: SimpleNamespace(wiki=SimpleNamespace(**full)),
    )

    c = TestClient(app)
    r = c.get("/api/v1/wiki/contradictions", params={"page_uid": "WikiPage:r:p.md"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
