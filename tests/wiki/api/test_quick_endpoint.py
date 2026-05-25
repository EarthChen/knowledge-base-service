"""HTTP tests for POST /api/v1/wiki/quick — T2.5."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import (
    WikiTaskRegistry,
    get_task_registry_dep,
    get_wiki_service_dep,
    wiki_router,
)
from wiki.cache import WikiCache


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_quick_app(
    *,
    mock_wiki: Any | None = None,
    repo_status: Any | None = None,
    wiki_cache: WikiCache | None = None,
    quick_background: Any | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.wiki_tasks = WikiTaskRegistry()
    app.state.wiki_cache = wiki_cache or WikiCache(max_size=100)

    svc = mock_wiki or MagicMock()

    async def override_wiki() -> Any:
        return svc

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.dependency_overrides[get_task_registry_dep] = override_registry

    if repo_status is not None:
        app.state.wiki_quick_repo_status = repo_status
    if quick_background is not None:
        app.state.wiki_quick_background = quick_background

    return app, TestClient(app)


class TestWikiQuick:
    def test_quick_valid_url(self) -> None:
        async def status(_git_url: str, _branch: str | None, _token: str | None) -> tuple[str, bool, int]:
            return ("new-repo", False, 0)

        mock_svc = MagicMock()
        _, client = _make_quick_app(mock_wiki=mock_svc, repo_status=status)

        r = client.post(
            "/api/v1/wiki/quick",
            json={"git_url": "https://gitlab.example.com/group/proj.git", "mode": "structure"},
        )
        assert r.status_code == 202
        body = r.json()
        assert "task_id" in body
        assert body["task_id"].startswith("wiki-quick-")
        assert body.get("status") == "pending"

    def test_quick_invalid_url_400(self) -> None:
        _, client = _make_quick_app()

        r = client.post(
            "/api/v1/wiki/quick",
            json={"git_url": "not-a-valid-remote", "mode": "structure"},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "kb_client_error"

    def test_quick_already_indexed(self) -> None:
        bundle = {
            "pages": [
                {
                    "path": "README.md",
                    "title": "Overview",
                    "page_type": "repo_overview",
                    "content": "",
                    "diagrams": [],
                    "source_locations": [],
                    "method_locations": [],
                    "metadata": {
                        "node_count": 0,
                        "edge_count": 0,
                        "generation_mode": "structure",
                        "fallback_tier": None,
                    },
                }
            ],
            "structure": {"repository": "indexed-r", "root": {}, "total_pages": 1},
            "stats": {"total_pages": 1, "generation_time_ms": 0},
            "degraded": False,
        }

        mock_svc = MagicMock()
        mock_svc.generate = AsyncMock(return_value=bundle)

        async def status(_git_url: str, _branch: str | None, _token: str | None) -> tuple[str, bool, int]:
            return ("indexed-r", True, 3)

        _, client = _make_quick_app(mock_wiki=mock_svc, repo_status=status)

        r = client.post(
            "/api/v1/wiki/quick",
            json={"git_url": "https://github.com/org/indexed-r.git", "mode": "structure"},
        )
        assert r.status_code == 200
        assert r.json()["pages"][0]["title"] == "Overview"
        mock_svc.generate.assert_awaited_once()


class TestWikiQuickAuth:
    def test_viewer_token_receives_403_when_auth_enforced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import core.auth as auth_mod

        registry = {"viewer-only": auth_mod.TokenInfo(role=auth_mod.Role.VIEWER)}
        monkeypatch.setattr(auth_mod, "_get_registry", lambda: registry)

        async def status(_git_url: str, _branch: str | None, _token: str | None) -> tuple[str, bool, int]:
            return ("new-repo", False, 0)

        _, client = _make_quick_app(repo_status=status)

        r = client.post(
            "/api/v1/wiki/quick",
            json={"git_url": "https://gitlab.example.com/group/proj.git", "mode": "structure"},
            headers={"Authorization": "Bearer viewer-only"},
        )
        assert r.status_code == 403

    def test_editor_token_allowed_when_auth_enforced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import core.auth as auth_mod

        registry = {"ed": auth_mod.TokenInfo(role=auth_mod.Role.EDITOR)}
        monkeypatch.setattr(auth_mod, "_get_registry", lambda: registry)

        async def status(_git_url: str, _branch: str | None, _token: str | None) -> tuple[str, bool, int]:
            return ("new-repo", False, 0)

        _, client = _make_quick_app(repo_status=status)

        r = client.post(
            "/api/v1/wiki/quick",
            json={"git_url": "https://gitlab.example.com/group/proj.git", "mode": "structure"},
            headers={"Authorization": "Bearer ed"},
        )
        assert r.status_code == 202
