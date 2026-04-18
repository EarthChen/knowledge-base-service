"""HTTP tests for wiki generation API — T2.2–T2.4."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from starlette.testclient import TestClient

import auth as auth_module
from api.routes.wiki_routes import WikiTaskRegistry, get_task_registry_dep, get_wiki_service_dep, wiki_router
from store.schema import GraphNode, NodeLabel
from wiki.exporter import WikiExporter
from wiki.models import PageType, WikiStructure, WikiStructureNode
from wiki.service import WikiService


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _detail_error(resp) -> str:
    body = resp.json().get("detail")
    if isinstance(body, dict):
        return body.get("error", "")
    if isinstance(body, list) and body:
        item = body[0]
        if isinstance(item, dict):
            return str(item.get("ctx", {}).get("error") or "")
    return ""


def _make_app(mock_wiki: Any | None = None) -> tuple[FastAPI, TestClient, Any]:
    app = FastAPI()
    app.state.wiki_tasks = WikiTaskRegistry()

    svc = mock_wiki or MagicMock()

    async def override_wiki() -> Any:
        return svc

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.dependency_overrides[get_task_registry_dep] = override_registry

    return app, TestClient(app), svc


class TestWikiGenerateSync:
    def test_generate_sync_200(self) -> None:
        mock_svc = MagicMock()
        mock_svc.generate = AsyncMock(
            return_value={
                "pages": [{"title": "Mod", "path": "modules/x.md"}],
                "structure": {"repository": "r1", "root": {}, "total_pages": 1},
                "stats": {"total_pages": 1, "generation_time_ms": 0},
                "degraded": False,
            }
        )
        _, client, _ = _make_app(mock_svc)
        r = client.post(
            "/api/v1/wiki/generate",
            json={
                "repository": "r1",
                "scope": "module:src/service.py",
                "mode": "structure",
                "format": "json",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["pages"][0]["title"] == "Mod"
        mock_svc.generate.assert_awaited_once()

    def test_generate_invalid_scope_400(self) -> None:
        _, client, mock_svc = _make_app()
        r = client.post(
            "/api/v1/wiki/generate",
            json={
                "repository": "r1",
                "scope": "not-a-valid-scope",
                "mode": "structure",
                "format": "json",
            },
        )
        assert r.status_code == 400
        assert _detail_error(r) == "invalid_scope"
        mock_svc.generate.assert_not_called()

    def test_generate_repo_not_found_404(self) -> None:
        mock_svc = MagicMock()

        async def boom(*_a: object, **_k: object) -> None:
            from wiki.service import WikiRepoNotFoundError

            raise WikiRepoNotFoundError("ghost-repo")

        mock_svc.generate = AsyncMock(side_effect=boom)
        _, client, _ = _make_app(mock_svc)
        r = client.post(
            "/api/v1/wiki/generate",
            json={
                "repository": "ghost-repo",
                "scope": "module:src/a.py",
                "mode": "structure",
                "format": "json",
            },
        )
        assert r.status_code == 404
        assert _detail_error(r) == "repo_not_found"

    def test_generate_structure_mode(self) -> None:
        llm = AsyncMock()
        graph = AsyncMock()
        mod = GraphNode(
            label=NodeLabel.MODULE,
            uid="m1",
            properties={"path": "src/m.py", "name": "m", "file": "src/m.py", "start_line": 1},
        )
        graph.find_node_by_path = AsyncMock(return_value=mod)
        graph.find_node_by_fqn = AsyncMock(return_value=None)
        graph.find_children = AsyncMock(return_value=[])
        graph.find_edges = AsyncMock(return_value=[])
        graph.find_node_by_uid = AsyncMock(return_value=None)
        graph.find_top_level_modules = AsyncMock(return_value=[])

        svc = WikiService(graph=graph, llm=llm, repository_exists=AsyncMock(return_value=True))
        root = WikiStructureNode(
            path="src/m.py",
            title="m",
            page_type=PageType.MODULE_OVERVIEW,
            children=[],
        )
        structure = WikiStructure(repository="r1", root=root, total_pages=1)

        async def gen(repo: str, scope: str, mode: str, fmt: str) -> dict:
            await svc._ensure_repo(repo)
            pages, deg = await svc._compose_all_pages(
                repo,
                structure,
                svc._config_for(mode, fmt, repo),
            )
            b = WikiExporter().export_json(pages, structure)
            b["degraded"] = deg
            return b

        mock_svc = MagicMock()
        mock_svc.generate = AsyncMock(side_effect=gen)
        _, client, _ = _make_app(mock_svc)

        r = client.post(
            "/api/v1/wiki/generate",
            json={
                "repository": "r1",
                "scope": "module:src/m.py",
                "mode": "structure",
                "format": "json",
            },
        )
        assert r.status_code == 200
        assert len(r.json()["pages"]) == 1
        llm.generate.assert_not_called()


class TestWikiStreaming:
    def test_generate_streaming(self) -> None:
        mock_svc = MagicMock()

        async def fake_events(*_a: object, **_k: object):
            yield {"page": {"title": "One", "path": "p.md"}}
            yield {"complete": {"pages": [], "structure": {}, "stats": {}, "degraded": False}}

        mock_svc.generate_stream_events = fake_events
        _, client, _ = _make_app(mock_svc)
        r = client.post(
            "/api/v1/wiki/generate",
            headers={"Accept": "text/event-stream"},
            json={
                "repository": "r1",
                "scope": "module:x",
                "mode": "structure",
                "format": "json",
            },
        )
        assert r.status_code == 200
        text = r.text
        assert "wiki-page" in text
        assert "wiki-complete" in text


class TestWikiTasks:
    def test_task_polling_lifecycle(self) -> None:
        mock_svc = MagicMock()
        mock_svc.generate = AsyncMock(
            return_value={
                "pages": [],
                "structure": {"repository": "r1", "root": {}, "total_pages": 0},
                "stats": {"total_pages": 0, "generation_time_ms": 0},
                "degraded": False,
            }
        )
        _, client, _ = _make_app(mock_svc)

        r = client.post(
            "/api/v1/wiki/generate",
            json={
                "repository": "r1",
                "scope": "repo",
                "mode": "structure",
                "format": "json",
            },
        )
        assert r.status_code == 202
        tid = r.json()["task_id"]
        assert r.json()["status"] == "pending"

        for _ in range(500):
            gr = client.get(f"/api/v1/wiki/tasks/{tid}")
            assert gr.status_code == 200
            st = gr.json()["status"]
            if st == "completed":
                break
            assert st in ("pending", "queued", "running")
        assert client.get(f"/api/v1/wiki/tasks/{tid}").json()["status"] == "completed"

    def test_task_not_found_404(self) -> None:
        _, client, _ = _make_app()
        r = client.get("/api/v1/wiki/tasks/wiki-does-not-exist")
        assert r.status_code == 404
        assert _detail_error(r) == "task_not_found"


class TestWikiConcurrency:
    @pytest.mark.asyncio
    async def test_concurrency_limit(self) -> None:
        """Sync TestClient can isolate event loops; use ASGITransport + AsyncClient."""

        class SlowWikiSvc:
            async def generate(self, *_a: object, **_k: object) -> dict:
                await asyncio.sleep(120.0)
                return {
                    "pages": [],
                    "structure": {},
                    "stats": {"total_pages": 0, "generation_time_ms": 0},
                    "degraded": False,
                }

        mock_svc = SlowWikiSvc()
        app, _sync_client, _ = _make_app(mock_svc)

        transport = ASGITransport(app=app)
        task_ids: list[str] = []
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(6):
                r = await client.post(
                    "/api/v1/wiki/generate",
                    json={
                        "repository": "r1",
                        "scope": "repo",
                        "mode": "structure",
                        "format": "json",
                    },
                )
                assert r.status_code == 202
                task_ids.append(r.json()["task_id"])

            await asyncio.sleep(0.12)

        registry = app.state.wiki_tasks
        statuses_fn = [registry.tasks[tid]["status"] for tid in task_ids]
        assert "queued" in statuses_fn
