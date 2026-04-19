"""Tests for graph community detection (label propagation)."""

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

    async def override_get_service() -> MagicMock:
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service
    return TestClient(app)


class TestCommunityDetector:
    @pytest.mark.asyncio
    async def test_detect_communities(self) -> None:
        from query.community_detection import CommunityDetector

        store = MagicMock()

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            if "community_nodes" in cypher:
                return QueryResultWrapper(
                    data=[
                        {"uid": "a", "name": "A", "typ": "Function", "file": "f1.py"},
                        {"uid": "b", "name": "B", "typ": "Function", "file": "f2.py"},
                        {"uid": "c", "name": "C", "typ": "Class", "file": "f3.py"},
                    ],
                    raw=[],
                )
            if "community_edges" in cypher:
                return QueryResultWrapper(
                    data=[
                        {"src": "a", "tgt": "b"},
                        {"src": "b", "tgt": "c"},
                        {"src": "a", "tgt": "c"},
                    ],
                    raw=[],
                )
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = AsyncMock(side_effect=router)
        det = CommunityDetector(store)
        out = await det.detect(repository=None, min_community_size=2)

        assert out["total_communities"] >= 1
        assert len(out["communities"]) >= 1
        first = out["communities"][0]
        assert "members" in first and len(first["members"]) >= 2

    @pytest.mark.asyncio
    async def test_communities_have_labels(self) -> None:
        from query.community_detection import CommunityDetector

        store = MagicMock()

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            if "community_nodes" in cypher:
                return QueryResultWrapper(
                    data=[
                        {"uid": "u1", "name": "Foo", "typ": "Function", "file": "a.py"},
                        {"uid": "u2", "name": "Bar", "typ": "Function", "file": "b.py"},
                        {"uid": "u3", "name": "Baz", "typ": "Class", "file": "c.py"},
                    ],
                    raw=[],
                )
            if "community_edges" in cypher:
                return QueryResultWrapper(
                    data=[
                        {"src": "u1", "tgt": "u2"},
                        {"src": "u2", "tgt": "u3"},
                    ],
                    raw=[],
                )
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = AsyncMock(side_effect=router)
        det = CommunityDetector(store)
        out = await det.detect(repository=None, min_community_size=2)

        for comm in out["communities"]:
            lbl = comm.get("label", "")
            assert isinstance(lbl, str)
            assert lbl.strip() != ""

    def test_community_api_endpoint(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()
        captured: dict[str, Any] = {}

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            if "community_nodes" in cypher:
                captured["repo_nodes"] = params.get("repository") if params else None
                return QueryResultWrapper(data=[], raw=[])
            if "community_edges" in cypher:
                captured["repo_edges"] = params.get("repository") if params else None
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.get("/api/v1/graph/communities")
        assert r.status_code == 200
        body = r.json()
        assert "communities" in body
        assert body["total_communities"] == 0
        assert body["unclustered_count"] == 0

    def test_community_by_repository(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()

        repos: list[Any] = []

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            if params and "repository" in params:
                repos.append(params.get("repository"))
            if "community_nodes" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            if "community_edges" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.get("/api/v1/graph/communities?repository=my-repo&min_size=4")
        assert r.status_code == 200
        assert repos.count("my-repo") >= 2
