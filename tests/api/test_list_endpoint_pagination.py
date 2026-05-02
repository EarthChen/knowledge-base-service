"""Tests for optional list pagination on viewer and business routes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import core.auth as auth_module
from api.error_handler import register_exception_handlers
from api.pagination import slice_page
from api.routes import business_routes, repository_routes
from main import _get_service, viewer_router
from store.falkordb_store import QueryResultWrapper


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def test_slice_page_limit_none_returns_tail() -> None:
    items = [{"i": x} for x in range(5)]
    window, total = slice_page(items, offset=2, limit=None)
    assert total == 5
    assert [d["i"] for d in window] == [2, 3, 4]


def test_slice_page_with_limit() -> None:
    items = [{"i": x} for x in range(10)]
    window, total = slice_page(items, offset=3, limit=2)
    assert total == 10
    assert [d["i"] for d in window] == [3, 4]


def test_slice_page_offset_beyond_total() -> None:
    items = [{"i": 0}]
    window, total = slice_page(items, offset=99, limit=5)
    assert total == 1
    assert window == []


@pytest.mark.asyncio
async def test_list_repositories_paginated() -> None:
    mock_svc = MagicMock()
    app = FastAPI()
    app.include_router(viewer_router)

    rows = [{"repository": f"repo{x}"} for x in range(5)]

    async def override_get_service():
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service

    with patch(
        "api.routes.repository_routes._enriched_repository_rows",
        new=AsyncMock(return_value=rows),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/api/v1/repositories", params={"offset": 1, "limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["offset"] == 1
    assert body["limit"] == 2
    assert [x["repository"] for x in body["repositories"]] == ["repo1", "repo2"]


@pytest.mark.asyncio
async def test_list_documents_paginated() -> None:
    mock_svc = MagicMock()
    app = FastAPI()
    app.include_router(viewer_router)

    doc_rows = [
        {
            "uid": "d1",
            "repository": "r1",
            "file": "/abs/r1/doc.md",
            "title": "Doc One",
            "content_hash": "h1",
            "sec_uid": None,
        },
        {
            "uid": "d2",
            "repository": "r1",
            "file": "/abs/r1/other.md",
            "title": "Doc Two",
            "content_hash": "h2",
            "sec_uid": None,
        },
        {
            "uid": "d3",
            "repository": "r2",
            "file": "/abs/r2/z.md",
            "title": "Zed",
            "content_hash": "h3",
            "sec_uid": None,
        },
    ]

    async def override_get_service():
        return mock_svc

    app.dependency_overrides[_get_service] = override_get_service

    with patch.object(
        repository_routes.GraphQueryRepository,
        "list_documents",
        new=AsyncMock(return_value=QueryResultWrapper(doc_rows)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/api/v1/documents", params={"offset": 1, "limit": 1})

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["offset"] == 1
    assert body["limit"] == 1
    assert len(body["documents"]) == 1
    assert body["documents"][0]["title"] == "Doc Two"


@pytest.mark.asyncio
async def test_list_businesses_includes_total_and_optional_window() -> None:
    graph = AsyncMock()

    async def query_side_effect(cypher: str, params: dict[str, Any] | None = None) -> MagicMock:
        if "MATCH (b:Business)" in cypher:
            return MagicMock(result_set=[
                ["b1", "One", "d1", "t1"],
                ["b2", "Two", "d2", "t2"],
                ["b3", "Three", "d3", "t3"],
            ])
        return MagicMock(result_set=[])

    graph.query = AsyncMock(side_effect=query_side_effect)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(business_routes.router)
    app.state.graph = graph

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r_all = await ac.get("/api/v1/businesses")
        r_page = await ac.get("/api/v1/businesses", params={"offset": 1, "limit": 2})

    assert r_all.status_code == 200
    all_body = r_all.json()
    assert all_body["total"] == 3
    assert len(all_body["businesses"]) == 3
    assert "offset" not in all_body

    assert r_page.status_code == 200
    page_body = r_page.json()
    assert page_body["total"] == 3
    assert page_body["offset"] == 1
    assert page_body["limit"] == 2
    names = [b["name"] for b in page_body["businesses"]]
    assert names == ["Two", "Three"]
