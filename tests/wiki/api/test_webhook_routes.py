"""HTTP tests for webhook routes (P3 SA-4)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock

import core.auth as auth
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.error_handler import register_exception_handlers
from api.routes.webhook_routes import init_webhook_state, webhook_router


def _github_sig(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _minimal_github_push_payload() -> dict[str, Any]:
    return {
        "ref": "refs/heads/main",
        "before": "1111111111111111111111111111111111111111",
        "after": "2222222222222222222222222222222222222222222",
        "repository": {"full_name": "o/r"},
        "sender": {"login": "u"},
        "commits": [{"added": [], "modified": ["a.py"], "removed": []}],
        "head_commit": {"timestamp": "2026-04-18T12:00:00Z"},
    }


@pytest.fixture
def webhook_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Open-access mode for tests (no configured API tokens → require_role allows callers).
    monkeypatch.setattr(auth, "_token_registry", {})

    app = FastAPI()
    register_exception_handlers(app)
    updater = AsyncMock()
    cfg = {
        "enabled": True,
        "debounce_seconds": 30,
        "auto_update_branches": ["main", "master"],
        "providers": {"github": {"secret": "gh-test-secret", "events": ["push"]}},
    }
    init_webhook_state(app, incremental_updater=updater, initial_config=cfg)
    app.include_router(webhook_router)
    return TestClient(app)


class TestReceiveWebhookGithub:
    def test_post_github_valid_signature_returns_202(self, webhook_client: TestClient) -> None:
        payload = _minimal_github_push_payload()
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-abc",
            "X-Hub-Signature-256": _github_sig("gh-test-secret", body),
            "Content-Type": "application/json",
        }
        r = webhook_client.post("/api/v1/hooks/github", content=body, headers=headers)
        assert r.status_code == 202
        data = r.json()
        assert data["status"] == "queued"
        assert data["delivery_id"] == "delivery-abc"

    def test_post_github_bad_signature_returns_401(self, webhook_client: TestClient) -> None:
        payload = _minimal_github_push_payload()
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-x",
            "X-Hub-Signature-256": _github_sig("wrong-secret", body),
            "Content-Type": "application/json",
        }
        r = webhook_client.post("/api/v1/hooks/github", content=body, headers=headers)
        assert r.status_code == 401

    def test_post_unknown_provider_returns_400(self, webhook_client: TestClient) -> None:
        r = webhook_client.post("/api/v1/hooks/bitbucket", content=b"{}")
        assert r.status_code == 400

    def test_post_github_non_push_returns_200_ignored(self, webhook_client: TestClient) -> None:
        payload = {"action": "opened", "repository": {"full_name": "a/b"}}
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-issues",
            "X-Hub-Signature-256": _github_sig("gh-test-secret", body),
            "Content-Type": "application/json",
        }
        r = webhook_client.post("/api/v1/hooks/github", content=body, headers=headers)
        assert r.status_code == 200
        assert r.json() == {"status": "ignored"}


class TestWebhookConfigEndpoints:
    def test_get_config_returns_current(self, webhook_client: TestClient) -> None:
        r = webhook_client.get("/api/v1/hooks/config")
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["debounce_seconds"] == 30
        assert data["auto_update_branches"] == ["main", "master"]
        assert data["providers"]["github"]["secret"] == "***configured***"

    def test_put_config_updates_state(self, webhook_client: TestClient) -> None:
        r = webhook_client.put(
            "/api/v1/hooks/config",
            json={
                "enabled": False,
                "debounce_seconds": 60,
                "auto_update_branches": ["develop"],
                "providers": {},
            },
        )
        assert r.status_code == 200
        got = r.json()
        assert got["enabled"] is False
        assert got["debounce_seconds"] == 60
        assert got["auto_update_branches"] == ["develop"]

        r2 = webhook_client.get("/api/v1/hooks/config")
        assert r2.json() == got
