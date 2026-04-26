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
from tests.wiki_config_inject import wiki_service_injection
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import WikiTaskRegistry, get_task_registry_dep, get_wiki_service_dep, wiki_router
from store.falkordb_store import QueryResultWrapper
from store.schema import GraphNode, NodeLabel
from wiki.exporter import WikiExporter
from wiki.models import PageType, WikiStructure, WikiStructureNode
from wiki.service import WikiService


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _err_code(resp) -> str:
    err = resp.json().get("error") or {}
    return str(err.get("code", ""))


def _make_app(
    mock_wiki: Any | None = None,
    *,
    wiki_store: Any | None = ...,
) -> tuple[FastAPI, TestClient, Any]:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.wiki_tasks = WikiTaskRegistry()

    svc = mock_wiki or MagicMock()

    async def override_wiki() -> Any:
        return svc

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.dependency_overrides[get_task_registry_dep] = override_registry

    if wiki_store is not ...:
        app.state.wiki_store = wiki_store

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
        assert _err_code(r) == "kb_client_error"
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
        assert _err_code(r) == "kb_not_found"

    def test_generate_structure_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            WikiService,
            "_enrich_pages_after_compose",
            AsyncMock(),
        )
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
        graph.list_repository_modules = AsyncMock(return_value=[])
        graph.find_module_import_edges = AsyncMock(return_value=[])
        graph.find_repository_calls_edges = AsyncMock(return_value=[])

        svc = WikiService(
            graph=graph, llm=llm, repository_exists=AsyncMock(return_value=True), **wiki_service_injection(),
        )
        root = WikiStructureNode(
            path="src/m.py",
            title="m",
            page_type=PageType.MODULE_OVERVIEW,
            children=[],
        )
        structure = WikiStructure(repository="r1", root=root, total_pages=1)

        async def gen(
            repo: str,
            scope: str,
            mode: str,
            fmt: str,
            language: str = "en",
            *,
            llm_provider: str | None = None,
        ) -> dict:
            await svc._ensure_repo(repo)
            composer = svc._composer_for(llm_provider)
            pages, deg = await svc._compose_all_pages(
                repo,
                structure,
                svc._config_for(mode, fmt, repo, language),
                composer,
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
        assert (r.json().get("error") or {}).get("message") == "task_not_found"


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


class TestWikiPagesGraphBacked:
    def test_list_pages_returns_persisted_rows(self) -> None:
        store = MagicMock()
        _rows = [
            {
                "path": "README.md",
                "title": "Repo",
                "page_type": "repo_overview",
            },
            {
                "path": "modules/src_foo.md",
                "title": "Mod",
                "page_type": "module_overview",
            },
            {
                "path": "classes/Bar.md",
                "title": "Bar",
                "page_type": "class_detail",
            },
        ]

        async def list_pages_cypher(
            cypher: str, params: dict | None = None,
        ) -> QueryResultWrapper:
            p = params or {}
            if "count(" in cypher and "total" in cypher.lower():
                return QueryResultWrapper(data=[{"total": 3}], raw=[])
            if "SKIP" in cypher.upper() and "LIMIT" in cypher.upper():
                return QueryResultWrapper(data=_rows, raw=[])
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = AsyncMock(side_effect=list_pages_cypher)
        _, client, mock_svc = _make_app(wiki_store=store)
        r = client.get("/api/v1/wiki/my-repo/pages")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert body["pages"][0]["scope"] == "repo"
        assert body["pages"][1]["scope"] == "module:src_foo"
        assert body["pages"][2]["scope"] == "class:Bar"
        mock_svc.generate.assert_not_called()
        assert store.execute_query.await_count == 2
        all_params = [c.args[1] for c in store.execute_query.await_args_list if len(c.args) > 1]
        assert any(p.get("skip") == 0 and p.get("limit") == 50 for p in all_params)

    def test_list_pages_pagination_skip_limit(self) -> None:
        store = MagicMock()

        async def list_pages_paged(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            p = params or {}
            if "count(" in cypher:
                return QueryResultWrapper(data=[{"total": 99}], raw=[])
            if "SKIP" in cypher.upper():
                assert p.get("skip") == 3
                assert p.get("limit") == 10
                return QueryResultWrapper(
                    data=[{"path": "only.md", "title": "One", "page_type": "module_overview"}],
                    raw=[],
                )
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = AsyncMock(side_effect=list_pages_paged)
        _, client, _ = _make_app(wiki_store=store)
        r = client.get("/api/v1/wiki/corp/pages?skip=3&limit=10")
        assert r.status_code == 200
        assert r.json()["total"] == 99
        assert len(r.json()["pages"]) == 1

    def test_list_pages_503_when_store_missing(self) -> None:
        _, client, _ = _make_app(wiki_store=None)
        r = client.get("/api/v1/wiki/r1/pages")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "kb_service_unavailable"

    def test_get_page_detail_reads_graph(self) -> None:
        node = MagicMock()
        node.properties = {
            "path": "README.md",
            "title": "Overview",
            "content": "# Hello",
            "generated_at": "2024-01-01T00:00:00Z",
        }
        store = MagicMock()
        store.execute_query = AsyncMock(
            return_value=QueryResultWrapper(data=[{"wp": node}], raw=[]),
        )
        _, client, mock_svc = _make_app(wiki_store=store)
        r = client.get("/api/v1/wiki/r1/pages/README.md")
        assert r.status_code == 200
        data = r.json()
        assert data["path"] == "README.md"
        assert data["title"] == "Overview"
        assert data["content"] == "# Hello"
        assert data["diagrams"] == []
        assert data["source_locations"] == []
        assert data["method_locations"] == []
        assert data["context"] == {"repository": "r1", "module": "", "page": "README.md"}
        assert data["generated_at"] == "2024-01-01T00:00:00Z"
        mock_svc.generate.assert_not_called()
        store.execute_query.assert_awaited_once()
        _cypher, params = store.execute_query.await_args.args
        assert params == {"repo": "r1", "path": "README.md"}

    def test_get_page_detail_dict_node_properties(self) -> None:
        store = MagicMock()
        store.execute_query = AsyncMock(
            return_value=QueryResultWrapper(
                data=[
                    {
                        "wp": {
                            "path": "classes/X.md",
                            "title": "X",
                            "content": "body",
                            "generated_at": None,
                        }
                    }
                ],
                raw=[],
            ),
        )
        _, client, _ = _make_app(wiki_store=store)
        r = client.get("/api/v1/wiki/r1/pages/classes%2FX.md")
        assert r.status_code == 200
        assert r.json()["path"] == "classes/X.md"

    def test_get_page_detail_404(self) -> None:
        store = MagicMock()
        store.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
        _, client, _ = _make_app(wiki_store=store)
        r = client.get("/api/v1/wiki/r1/pages/missing.md")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "kb_not_found"

    def test_get_page_detail_503_when_store_missing(self) -> None:
        _, client, _ = _make_app(wiki_store=None)
        r = client.get("/api/v1/wiki/r1/pages/README.md")
        assert r.status_code == 503
