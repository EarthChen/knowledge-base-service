"""Tests for business API routes (repository binding)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import core.auth as auth
from api.error_handler import register_exception_handlers
from api.routes import business_routes


@pytest.fixture
def open_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_token_registry", {})
    monkeypatch.setenv("REQUIRE_AUTH", "false")


@pytest.fixture
def mock_graph() -> AsyncMock:
    graph = AsyncMock()

    async def query_side_effect(cypher: str, params: dict[str, Any] | None = None) -> MagicMock:
        if (
            "MATCH (b:Business {uid: $bid}) RETURN b.uid" in cypher
            or cypher.strip().startswith("MATCH (b:Business {uid: $bid}) RETURN b.uid")
        ):
            return MagicMock(result_set=[["business:test"]])
        return MagicMock(result_set=[])

    graph.query = AsyncMock(side_effect=query_side_effect)
    return graph


@pytest.fixture
def app(open_auth: None, mock_graph: AsyncMock) -> FastAPI:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(business_routes.router)
    application.state.graph = mock_graph
    return application


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_bind_repositories_empty_list_returns_400(client: AsyncClient) -> None:
    r = await client.put(
        "/api/v1/businesses/business:test/repositories",
        json={"repositories": []},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "repositories list must not be empty; use DELETE to unbind"
    )


@pytest.mark.asyncio
async def test_bind_repositories_valid_list_succeeds(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put(
            "/api/v1/businesses/business:test/repositories",
            json={"repositories": ["repo-a", "repo-b"]},
        )
    assert r.status_code == 200
    assert r.json() == {
        "business_id": "business:test",
        "repositories": ["repo-a", "repo-b"],
    }


@pytest.mark.asyncio
async def test_bind_repositories_runs_two_graph_queries_after_existence_check(
    app: FastAPI, mock_graph: AsyncMock
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.put(
            "/api/v1/businesses/business:test/repositories",
            json={"repositories": ["r1"]},
        )

    calls = [c.args[0] for c in mock_graph.query.call_args_list]
    assert len(calls) == 3
    assert calls[0] == "MATCH (b:Business {uid: $bid}) RETURN b.uid"
    assert calls[1] == "MATCH (b:Business {uid: $bid})-[r:CONTAINS_REPO]->() DELETE r"
    assert calls[2] == (
        "MATCH (b:Business {uid: $bid}) "
        "UNWIND $repos AS repo_name "
        "MERGE (r:Repository {name: repo_name}) "
        "MERGE (b)-[:CONTAINS_REPO]->(r)"
    )
