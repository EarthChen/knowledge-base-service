"""Security and defaults for webhook HTTP routes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import auth
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.error_handler import register_exception_handlers
from api.routes.webhook_routes import init_webhook_state, webhook_router
from auth import TokenInfo


def _ingest_push_body() -> dict[str, Any]:
    return {
        "repository": "org/repo",
        "payload": {
            "commits": [{"added": [], "modified": ["a.py"], "removed": []}],
        },
    }


def _client_with_ingest_mocks(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    updater = AsyncMock()
    cfg = {
        "enabled": False,
        "debounce_seconds": 30,
        "auto_update_branches": ["main"],
        "providers": {},
    }
    init_webhook_state(app, incremental_updater=updater, initial_config=cfg)

    detector = AsyncMock()
    detector.detect_from_file_list = AsyncMock(return_value=["page1"])
    app.state.change_detector = detector

    svc = AsyncMock()
    svc.bump_affected_wiki_pages = AsyncMock(
        return_value={"pages_regenerated": 1, "pages_total": 1},
    )
    app.state.wiki_service_factory = lambda: svc

    app.include_router(webhook_router)
    return TestClient(app)


def test_git_config_ssl_verify_defaults_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIT__SSL_VERIFY", raising=False)
    from config import GitConfig

    assert GitConfig().ssl_verify is True


class TestWikiIngestPushAuth:
    def test_ingest_push_allowed_open_mode_without_auth(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(auth, "_token_registry", {})
        client = _client_with_ingest_mocks(monkeypatch)
        r = client.post("/api/v1/hooks/ingest/push", json=_ingest_push_body())
        assert r.status_code == 200

    def test_ingest_push_forbidden_for_viewer_when_tokens_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            auth,
            "_token_registry",
            {"v-tok": TokenInfo(role=auth.Role.VIEWER), "e-tok": TokenInfo(role=auth.Role.EDITOR)},
        )
        client = _client_with_ingest_mocks(monkeypatch)
        r = client.post(
            "/api/v1/hooks/ingest/push",
            json=_ingest_push_body(),
            headers={"Authorization": "Bearer v-tok"},
        )
        assert r.status_code == 403

    def test_ingest_push_ok_for_editor_when_tokens_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            auth,
            "_token_registry",
            {"v-tok": TokenInfo(role=auth.Role.VIEWER), "e-tok": TokenInfo(role=auth.Role.EDITOR)},
        )
        client = _client_with_ingest_mocks(monkeypatch)
        r = client.post(
            "/api/v1/hooks/ingest/push",
            json=_ingest_push_body(),
            headers={"Authorization": "Bearer e-tok"},
        )
        assert r.status_code == 200

    def test_ingest_push_401_when_tokens_configured_but_missing_auth(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            auth,
            "_token_registry",
            {"e-tok": TokenInfo(role=auth.Role.EDITOR)},
        )
        client = _client_with_ingest_mocks(monkeypatch)
        r = client.post("/api/v1/hooks/ingest/push", json=_ingest_push_body())
        assert r.status_code == 401
