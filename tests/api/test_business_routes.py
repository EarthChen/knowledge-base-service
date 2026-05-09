"""Tests for business API routes (Redis-backed BusinessManager)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import api.kb_state as kb_state
import core.auth as auth
from api.error_handler import register_exception_handlers
from api.routes import business_routes


@pytest.fixture
def open_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_token_registry", {})
    monkeypatch.setenv("REQUIRE_AUTH", "false")


@pytest.fixture
def mock_bm() -> MagicMock:
    bm = MagicMock()
    bm.list_businesses.return_value = [
        {"id": "default", "name": "Default", "description": "", "created_at": 1000.0},
    ]
    bm.get_business.return_value = {"id": "test-biz", "name": "Test", "description": "", "created_at": 1000.0}
    bm.create_business.return_value = {"id": "test-biz", "name": "Test", "description": "", "created_at": 1000.0}
    bm.update_business.return_value = {"id": "test-biz", "name": "Updated", "description": "", "created_at": 1000.0}
    bm.delete_business.return_value = True
    bm.get_repos.return_value = []
    bm.set_repos.return_value = ["repo-a", "repo-b"]
    return bm


@pytest.fixture
def app(open_auth: None, mock_bm: MagicMock) -> FastAPI:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(business_routes.router)

    mock_registry = MagicMock()
    mock_registry.business_manager = mock_bm
    with patch.object(kb_state, "registry", mock_registry):
        yield application


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_businesses_returns_from_manager(client: AsyncClient) -> None:
    r = await client.get("/api/v1/businesses")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["businesses"][0]["id"] == "default"


@pytest.mark.asyncio
async def test_create_business_returns_201(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/businesses",
        json={"id": "test-biz", "name": "Test", "description": "A test business"},
    )
    assert r.status_code == 201
    assert r.json()["id"] == "test-biz"


@pytest.mark.asyncio
async def test_create_business_duplicate_returns_409(app: FastAPI, mock_bm: MagicMock) -> None:
    mock_bm.create_business.side_effect = ValueError("Business 'test-biz' already exists")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/businesses",
            json={"id": "test-biz", "name": "Test"},
        )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_update_business_returns_updated(client: AsyncClient) -> None:
    r = await client.put(
        "/api/v1/businesses/test-biz",
        json={"name": "Updated"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Updated"


@pytest.mark.asyncio
async def test_update_business_not_found(app: FastAPI, mock_bm: MagicMock) -> None:
    mock_bm.update_business.return_value = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put(
            "/api/v1/businesses/nonexistent",
            json={"name": "New"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_business_returns_deleted(client: AsyncClient) -> None:
    r = await client.delete("/api/v1/businesses/test-biz")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_bind_repositories_valid_list_succeeds(client: AsyncClient) -> None:
    r = await client.put(
        "/api/v1/businesses/test-biz/repositories",
        json={"repositories": ["repo-a", "repo-b"]},
    )
    assert r.status_code == 200
    assert r.json()["repositories"] == ["repo-a", "repo-b"]


@pytest.mark.asyncio
async def test_bind_repositories_not_found(app: FastAPI, mock_bm: MagicMock) -> None:
    mock_bm.get_business.return_value = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put(
            "/api/v1/businesses/nonexistent/repositories",
            json={"repositories": ["repo-a"]},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_repositories(client: AsyncClient, mock_bm: MagicMock) -> None:
    mock_bm.get_repos.return_value = ["repo-x"]
    r = await client.get("/api/v1/businesses/test-biz/repositories")
    assert r.status_code == 200
    assert r.json()["repositories"] == ["repo-x"]
