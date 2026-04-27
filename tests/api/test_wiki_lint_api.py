"""Tests for POST /api/v1/wiki/{repository}/lint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import (
    WikiTaskRegistry,
    get_task_registry_dep,
    get_wiki_lint_service_dep,
    get_wiki_service_dep,
    wiki_router,
)
from wiki.lint import WikiLintService
from wiki.service import WikiRepoNotFoundError


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def wiki_lint_client() -> tuple[TestClient, MagicMock]:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.wiki_tasks = WikiTaskRegistry()

    mock_wiki = MagicMock()
    mock_wiki.ensure_repository = AsyncMock(return_value=None)

    mock_lint = MagicMock(spec=WikiLintService)

    async def _fake_run_lint(repo: str, scope: str = "all") -> dict:
        return {
            "issues": [],
            "stats": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
            "checked_at": "2026-01-01T00:00:00+00:00",
            "scope": scope,
            "auto_heal": None,
        }

    mock_lint.run_lint = AsyncMock(side_effect=_fake_run_lint)

    async def override_wiki() -> MagicMock:
        return mock_wiki

    async def override_lint() -> MagicMock:
        return mock_lint

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_wiki_lint_service_dep] = override_lint
    app.dependency_overrides[get_task_registry_dep] = override_registry

    return TestClient(app), mock_lint


def test_post_wiki_lint_returns_200(wiki_lint_client: tuple[TestClient, MagicMock]) -> None:
    client, mock_lint = wiki_lint_client
    r = client.post("/api/v1/wiki/myrepo/lint", json={"scope": "all"})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "all"
    assert "issues" in body
    assert "stats" in body
    assert "checked_at" in body
    assert body.get("auto_heal") is None
    mock_lint.run_lint.assert_awaited_once()


def test_post_wiki_lint_missing_repo_returns_404() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.wiki_tasks = WikiTaskRegistry()

    mock_wiki = MagicMock()
    mock_wiki.ensure_repository = AsyncMock(side_effect=WikiRepoNotFoundError("missing"))

    mock_lint = MagicMock(spec=WikiLintService)

    async def override_wiki() -> MagicMock:
        return mock_wiki

    async def override_lint() -> MagicMock:
        return mock_lint

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_wiki_lint_service_dep] = override_lint
    app.dependency_overrides[get_task_registry_dep] = lambda: app.state.wiki_tasks

    client = TestClient(app)
    r = client.post("/api/v1/wiki/missing/lint", json={})
    assert r.status_code == 404
