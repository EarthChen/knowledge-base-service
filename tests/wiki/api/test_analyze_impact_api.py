"""HTTP tests for POST /api/v1/wiki/{repository}/analyze-impact — P3 SA-9."""

from __future__ import annotations

from typing import Any
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
from wiki.service import WikiRepoNotFoundError, WikiService


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _detail_error(resp: Any) -> str:
    body = resp.json().get("detail")
    if isinstance(body, dict):
        return str(body.get("error", "") or "")
    return ""


def _make_analyze_app(
    *,
    mock_wiki: Any | None = None,
    graph_query_service: Any | None = None,
) -> tuple[FastAPI, TestClient, Any]:
    app = FastAPI()
    app.state.wiki_tasks = WikiTaskRegistry()
    app.state.graph_query_service = graph_query_service

    svc = mock_wiki if mock_wiki is not None else MagicMock()

    async def override_wiki() -> Any:
        return svc

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.dependency_overrides[get_task_registry_dep] = override_registry

    return app, TestClient(app), svc


class TestAnalyzeImpactApi:
    def test_analyze_impact_200(self) -> None:
        mock_graph = MagicMock()
        mock_graph.analyze_pr_impact = AsyncMock(
            return_value={
                "affected_pages": [
                    {
                        "wiki_page_path": "modules/auth/AuthService",
                        "impact_level": "high",
                        "reason": "3 entities directly modified",
                        "affected_entities": ["AuthService", "TokenValidator"],
                    },
                ],
                "summary": {
                    "high_impact": 2,
                    "medium_impact": 3,
                    "total_affected_pages": 5,
                },
            },
        )
        wiki = MagicMock()
        wiki.ensure_repository = AsyncMock()

        _, client, _ = _make_analyze_app(mock_wiki=wiki, graph_query_service=mock_graph)

        r = client.post(
            "/api/v1/wiki/my-repo/analyze-impact",
            json={
                "changed_files": [
                    {"path": "src/AuthService.java", "status": "modified"},
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["affected_pages"][0]["wiki_page_path"] == "modules/auth/AuthService"
        assert body["affected_pages"][0]["impact_level"] == "high"
        assert body["affected_pages"][0]["affected_entities"] == ["AuthService", "TokenValidator"]
        assert body["summary"]["high_impact"] == 2
        assert body["summary"]["medium_impact"] == 3
        assert body["summary"]["total_affected_pages"] == 5
        wiki.ensure_repository.assert_awaited_once_with("my-repo")
        mock_graph.analyze_pr_impact.assert_awaited_once_with(
            repository="my-repo",
            changed_files=[{"path": "src/AuthService.java", "status": "modified"}],
        )

    def test_empty_changed_files_no_graph_call(self) -> None:
        mock_graph = MagicMock()
        mock_graph.analyze_pr_impact = AsyncMock()
        wiki = MagicMock()
        wiki.ensure_repository = AsyncMock()

        _, client, _ = _make_analyze_app(mock_wiki=wiki, graph_query_service=mock_graph)

        r = client.post(
            "/api/v1/wiki/my-repo/analyze-impact",
            json={"changed_files": []},
        )
        assert r.status_code == 200
        assert r.json() == {
            "affected_pages": [],
            "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
        }
        mock_graph.analyze_pr_impact.assert_not_called()
        wiki.ensure_repository.assert_not_called()

    def test_empty_changed_files_without_graph_configured(self) -> None:
        wiki = MagicMock()
        wiki.ensure_repository = AsyncMock()

        _, client, _ = _make_analyze_app(mock_wiki=wiki, graph_query_service=None)

        r = client.post(
            "/api/v1/wiki/my-repo/analyze-impact",
            json={"changed_files": []},
        )
        assert r.status_code == 200
        wiki.ensure_repository.assert_not_called()

    def test_invalid_status_422(self) -> None:
        mock_graph = MagicMock()
        mock_graph.analyze_pr_impact = AsyncMock()
        wiki = MagicMock()
        wiki.ensure_repository = AsyncMock()

        _, client, _ = _make_analyze_app(mock_wiki=wiki, graph_query_service=mock_graph)

        r = client.post(
            "/api/v1/wiki/my-repo/analyze-impact",
            json={
                "changed_files": [
                    {"path": "x.java", "status": "M"},
                ],
            },
        )
        assert r.status_code == 422
        mock_graph.analyze_pr_impact.assert_not_called()

    def test_repository_not_found_404(self) -> None:
        mock_graph = MagicMock()
        mock_graph.analyze_pr_impact = AsyncMock()

        async def boom(repo: str) -> None:
            raise WikiRepoNotFoundError(repo)

        wiki = MagicMock()
        wiki.ensure_repository = AsyncMock(side_effect=boom)

        _, client, _ = _make_analyze_app(mock_wiki=wiki, graph_query_service=mock_graph)

        r = client.post(
            "/api/v1/wiki/ghost-repo/analyze-impact",
            json={
                "changed_files": [
                    {"path": "a.py", "status": "added"},
                ],
            },
        )
        assert r.status_code == 404
        assert _detail_error(r) == "repo_not_found"
        mock_graph.analyze_pr_impact.assert_not_called()

    def test_graph_service_unconfigured_503(self) -> None:
        wiki = MagicMock()
        wiki.ensure_repository = AsyncMock()

        _, client, _ = _make_analyze_app(mock_wiki=wiki, graph_query_service=None)

        r = client.post(
            "/api/v1/wiki/my-repo/analyze-impact",
            json={
                "changed_files": [
                    {"path": "a.py", "status": "modified"},
                ],
            },
        )
        assert r.status_code == 503
        assert _detail_error(r) == "service_unavailable"

    def test_graph_analyze_raises_503(self) -> None:
        mock_graph = MagicMock()
        mock_graph.analyze_pr_impact = AsyncMock(side_effect=RuntimeError("neo4j down"))

        wiki = MagicMock()
        wiki.ensure_repository = AsyncMock()

        _, client, _ = _make_analyze_app(mock_wiki=wiki, graph_query_service=mock_graph)

        r = client.post(
            "/api/v1/wiki/my-repo/analyze-impact",
            json={
                "changed_files": [
                    {"path": "a.py", "status": "modified"},
                ],
            },
        )
        assert r.status_code == 503
        detail = r.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("error") == "graph_query_failed"
        assert "neo4j down" in str(detail.get("detail", ""))


class TestAnalyzeImpactIntegrationWikiService:
    def test_ensure_repository_with_real_wiki_service(self) -> None:
        mock_graph = MagicMock()
        mock_graph.analyze_pr_impact = AsyncMock(
            return_value={
                "affected_pages": [],
                "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
            },
        )

        svc = WikiService(
            graph=MagicMock(),
            llm=None,
            repository_exists=AsyncMock(return_value=True),
        )

        _, client, _ = _make_analyze_app(mock_wiki=svc, graph_query_service=mock_graph)

        r = client.post(
            "/api/v1/wiki/indexed-repo/analyze-impact",
            json={"changed_files": [{"path": "x.py", "status": "renamed"}]},
        )
        assert r.status_code == 200
        mock_graph.analyze_pr_impact.assert_awaited_once()
