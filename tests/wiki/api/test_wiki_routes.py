"""HTTP tests for wiki pages/navigation graph-backed API."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.routes.wiki_routes import WikiTaskRegistry, get_task_registry_dep, get_wiki_service_dep, wiki_router
from store.falkordb_store import QueryResultWrapper


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
        assert store.execute_query.await_count == 3
        first_args = store.execute_query.await_args_list[0].args
        assert first_args[1] == {"repo": "r1", "path": "README.md"}

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

    def test_get_navigation_returns_parsed_json(self) -> None:
        payload = {
            "parent_path": "modules/x",
            "parent_title": "x",
            "sibling_paths": [],
            "child_paths": [],
            "related_flow_paths": [],
            "breadcrumbs": [["Repo", "README.md"]],
        }
        store = MagicMock()
        store.execute_query = AsyncMock(
            return_value=QueryResultWrapper(
                data=[{"navigation_json": json.dumps(payload)}],
                raw=[],
            ),
        )
        _, client, _ = _make_app(wiki_store=store)
        r = client.get(
            "/api/v1/wiki/my-repo/navigation",
            params={"path": "classes/Foo.md"},
        )
        assert r.status_code == 200
        assert r.json() == payload
        _cypher, params = store.execute_query.await_args.args
        assert params == {"repo": "my-repo", "path": "classes/Foo.md"}

    def test_get_navigation_empty_defaults_when_unset(self) -> None:
        store = MagicMock()
        store.execute_query = AsyncMock(
            return_value=QueryResultWrapper(data=[{"navigation_json": ""}], raw=[]),
        )
        _, client, _ = _make_app(wiki_store=store)
        r = client.get("/api/v1/wiki/r1/navigation", params={"path": "a.md"})
        assert r.status_code == 200
        d = r.json()
        assert d["parent_path"] is None
        assert d["breadcrumbs"] == []
        assert d["sibling_paths"] == []

    def test_get_navigation_404_when_missing_page(self) -> None:
        store = MagicMock()
        store.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
        _, client, _ = _make_app(wiki_store=store)
        r = client.get("/api/v1/wiki/r1/navigation", params={"path": "nope.md"})
        assert r.status_code == 404

    def test_get_navigation_503_when_store_missing(self) -> None:
        _, client, _ = _make_app(wiki_store=None)
        r = client.get("/api/v1/wiki/r1/navigation", params={"path": "a.md"})
        assert r.status_code == 503
