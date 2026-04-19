"""HTTP tests for POST /api/v1/graph/expand — progressive graph neighbor expansion."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from main import _get_service, viewer_router
from store.falkordb_store import QueryResultWrapper


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_client(mock_svc: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(viewer_router)

    async def override_get_service():
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service
    return TestClient(app)


def _neighbor_row() -> dict:
    return {
        "uid": "n1",
        "name": "callee",
        "type": "Function",
        "file": "a.py",
        "line": 10,
        "end_line": 12,
        "signature": "def callee(): ...",
        "docstring": "",
    }


class TestGraphExpandApi:
    def test_expand_returns_neighbors(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()

        async def router(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            p = params or {}
            if "RETURN center.uid AS uid LIMIT 1" in cypher:
                return QueryResultWrapper(data=[{"uid": "center-uid"}], raw=[])
            if "MATCH path = (center)-[:" in cypher and "nbr" in cypher:
                return QueryResultWrapper(data=[_neighbor_row()], raw=[])
            if "MATCH (a)-[rel]->(b)" in cypher:
                return QueryResultWrapper(
                    data=[{"source": "center-uid", "target": "n1", "rel_type": "CALLS"}],
                    raw=[],
                )
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.post(
            "/api/v1/graph/expand",
            json={"node_name": "foo"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["center_uid"] == "center-uid"
        assert len(body["nodes"]) == 1
        assert body["nodes"][0]["id"] == "n1"
        assert body["nodes"][0]["name"] == "callee"
        assert len(body["edges"]) == 1
        assert body["edges"][0]["type"] == "CALLS"

    def test_expand_respects_limit(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()

        calls: list[tuple[str, dict | None]] = []

        async def router(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            calls.append((cypher, params))
            if "RETURN center.uid AS uid LIMIT 1" in cypher:
                return QueryResultWrapper(data=[{"uid": "c"}], raw=[])
            if "MATCH path = (center)-[:" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            if "MATCH (a)-[rel]->(b)" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.post(
            "/api/v1/graph/expand",
            json={"node_name": "foo", "limit": 7},
        )
        assert r.status_code == 200

        neighbor_params = next(p for c, p in calls if "MATCH path = (center)-[:" in c)
        assert neighbor_params["limit"] == 7

    def test_expand_excludes_existing(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()

        captured: dict[str, Any] = {}

        async def router(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            p = params or {}
            if "RETURN center.uid AS uid LIMIT 1" in cypher:
                return QueryResultWrapper(data=[{"uid": "c"}], raw=[])
            if "MATCH path = (center)-[:" in cypher:
                captured["exclude"] = list(p.get("exclude_uids") or [])
                return QueryResultWrapper(data=[], raw=[])
            if "MATCH (a)-[rel]->(b)" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.post(
            "/api/v1/graph/expand",
            json={
                "node_name": "foo",
                "exclude_uids": ["a", "b"],
            },
        )
        assert r.status_code == 200
        assert captured["exclude"] == ["a", "b"]

    def test_expand_depth_1(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()

        cyphers: list[str] = []

        async def router(cypher: str, params: dict | None = None) -> QueryResultWrapper:
            cyphers.append(cypher)
            if "RETURN center.uid AS uid LIMIT 1" in cypher:
                return QueryResultWrapper(data=[{"uid": "c"}], raw=[])
            if "MATCH path = (center)-[:" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            if "MATCH (a)-[rel]->(b)" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.post(
            "/api/v1/graph/expand",
            json={"node_name": "foo", "depth": 1},
        )
        assert r.status_code == 200
        neighbor_q = next(c for c in cyphers if "MATCH path = (center)-[:" in c)
        assert "*1..1]" in neighbor_q
