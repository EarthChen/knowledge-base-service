"""Tests for blast-radius impact analysis (query + API)."""

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


def _center_row(uid: str, name: str) -> dict[str, Any]:
    return {
        "uid": uid,
        "name": name,
        "typ": "Function",
        "file": "svc.py",
        "line": 1,
    }


def _nbr_row(
    uid: str,
    name: str,
    rel: str,
    typ: str = "Function",
) -> dict[str, Any]:
    return {
        "uid": uid,
        "name": name,
        "typ": typ,
        "file": "x.py",
        "line": 2,
        "relation": rel,
    }


class TestBlastRadiusAnalyzer:
    @pytest.mark.asyncio
    async def test_blast_radius_returns_affected_nodes(self) -> None:
        from query.blast_radius import BlastRadiusAnalyzer

        store = MagicMock()
        calls: list[str] = []

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            calls.append(cypher)
            p = params or {}
            if "n.fqn = $fqn OR n.name = $simple_name" in cypher and "n:Function OR n:Class OR n:Module" in cypher:
                return QueryResultWrapper(data=[_center_row("u0", "changed")], raw=[])
            if "(nbr)-[r:CALLS|IMPORTS|INHERITS]->(entity)" in cypher:
                return QueryResultWrapper(
                    data=[
                        _nbr_row("u1", "caller_a", "CALLS"),
                        _nbr_row("u2", "Sub", "INHERITS", "Class"),
                    ],
                    raw=[],
                )
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = AsyncMock(side_effect=router)
        analyzer = BlastRadiusAnalyzer(store)
        result = await analyzer.analyze(["changed"], max_depth=3, repository=None)

        assert result["center_entities"]
        assert result["center_entities"][0]["uid"] == "u0"
        affected_flat = [
            n for layer in result["affected"] for n in layer["nodes"]
        ]
        uids = {n["uid"] for n in affected_flat}
        assert "u1" in uids and "u2" in uids

    @pytest.mark.asyncio
    async def test_blast_radius_depth_levels(self) -> None:
        from query.blast_radius import BlastRadiusAnalyzer

        store = MagicMock()
        frontier_calls = 0

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            nonlocal frontier_calls
            if "n.fqn = $fqn OR n.name = $simple_name" in cypher:
                return QueryResultWrapper(data=[_center_row("c0", "root")], raw=[])
            if "(nbr)-[r:CALLS|IMPORTS|INHERITS]->(entity)" in cypher:
                frontier_calls += 1
                uids = params.get("uids") if params else []
                if uids == ["c0"]:
                    return QueryResultWrapper(data=[_nbr_row("c1", "hop1", "CALLS")], raw=[])
                if uids == ["c1"]:
                    return QueryResultWrapper(data=[_nbr_row("c2", "hop2", "IMPORTS")], raw=[])
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = AsyncMock(side_effect=router)
        analyzer = BlastRadiusAnalyzer(store)
        result = await analyzer.analyze(["root"], max_depth=3, repository=None)

        depths = {layer["depth"]: len(layer["nodes"]) for layer in result["affected"]}
        assert 1 in depths and depths[1] >= 1
        assert 2 in depths and depths[2] >= 1
        assert frontier_calls >= 2

    @pytest.mark.asyncio
    async def test_blast_radius_confidence_scores(self) -> None:
        from query.blast_radius import BlastRadiusAnalyzer

        store = MagicMock()

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            if "n.fqn = $fqn OR n.name = $simple_name" in cypher:
                return QueryResultWrapper(data=[_center_row("a", "x")], raw=[])
            if "(nbr)-[r:CALLS|IMPORTS|INHERITS]->(entity)" in cypher:
                return QueryResultWrapper(data=[_nbr_row("b", "y", "CALLS")], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = AsyncMock(side_effect=router)
        analyzer = BlastRadiusAnalyzer(store)
        result = await analyzer.analyze(["x"], max_depth=2, repository=None)

        node = next(
            n
            for layer in result["affected"]
            for n in layer["nodes"]
            if n["uid"] == "b"
        )
        assert "confidence" in node
        assert isinstance(node["confidence"], (int, float))
        assert 0 < float(node["confidence"]) <= 1.0


class TestBlastRadiusApi:
    def test_blast_radius_api_endpoint(self) -> None:
        mock_svc = MagicMock()
        mock_svc.store = MagicMock()

        async def router(cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
            if "n.fqn = $fqn OR n.name = $simple_name" in cypher:
                return QueryResultWrapper(data=[_center_row("z1", "fn")], raw=[])
            if "(nbr)-[r:CALLS|IMPORTS|INHERITS]->(entity)" in cypher:
                return QueryResultWrapper(data=[], raw=[])
            return QueryResultWrapper(data=[], raw=[])

        mock_svc.store.execute_query = AsyncMock(side_effect=router)

        client = _make_client(mock_svc)
        r = client.post(
            "/api/v1/graph/blast-radius",
            json={"entity_names": ["fn"], "max_depth": 2},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["center_entities"][0]["name"] == "fn"
        assert body["total_affected"] == 0
        assert "summary" in body
