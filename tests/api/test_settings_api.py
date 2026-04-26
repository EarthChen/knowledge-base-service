"""Tests for settings API endpoints."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import api.routes.settings_routes as settings_routes_module
import services.settings_crypto as settings_crypto
import services.settings_service as settings_service_module
from auth import Role, TokenInfo
from config import get_settings


@pytest.fixture(autouse=True)
def clear_get_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reload_crypto_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)
    importlib.reload(settings_crypto)
    importlib.reload(settings_service_module)
    importlib.reload(settings_routes_module)


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    """Create a FastAPI app with settings router using temp DB."""
    db_path = str(tmp_path / "test_settings.db")

    from services.settings_service import SettingsService
    from store.settings_store import SettingsStore

    def _get_service() -> SettingsService:
        return SettingsService(SettingsStore(db_path))

    application = FastAPI()
    application.include_router(settings_routes_module.settings_router)
    application.dependency_overrides[settings_routes_module._get_service] = _get_service

    async def _admin_auth_override() -> TokenInfo | None:
        """Treat requests as admin in this isolated app (env may have real API tokens)."""
        return TokenInfo(role=Role.ADMIN)

    application.dependency_overrides[
        settings_routes_module.require_settings_admin
    ] = _admin_auth_override
    return application


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


class TestGetSettings:
    @pytest.mark.asyncio
    async def test_get_all_returns_categories(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        cats = data["categories"]
        assert isinstance(cats, dict)

    @pytest.mark.asyncio
    async def test_get_category(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/settings/system")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "system"

    @pytest.mark.asyncio
    async def test_get_nonexistent_category(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/settings/nonexistent_category_xyz")
        assert resp.status_code == 404


class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_batch_update(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/v1/settings",
            json={
                "settings": [
                    {"key": "host", "value": "127.0.0.1", "category": "system"},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_single_update(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/v1/settings/host",
            json={"value": "127.0.0.1", "category": "system"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_then_read(self, client: AsyncClient) -> None:
        await client.put(
            "/api/v1/settings",
            json={
                "settings": [
                    {"key": "host", "value": "10.0.0.1", "category": "system"},
                ]
            },
        )
        resp = await client.get("/api/v1/settings/system")
        data = resp.json()
        host_setting = data["settings"].get("host", {})
        assert host_setting.get("value") == "10.0.0.1"
        assert host_setting.get("source") == "db"

    @pytest.mark.asyncio
    async def test_batch_unknown_key_returns_400(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/v1/settings",
            json={
                "settings": [
                    {"key": "not.a.real.setting.key", "value": "x", "category": "system"},
                ]
            },
        )
        assert resp.status_code == 400
        assert "Unknown setting key" in resp.json().get("detail", "")


class TestDeleteSetting:
    @pytest.mark.asyncio
    async def test_delete_existing(self, client: AsyncClient) -> None:
        await client.put(
            "/api/v1/settings",
            json={"settings": [{"key": "host", "value": "192.168.1.1", "category": "system"}]},
        )
        resp = await client.delete("/api/v1/settings/host")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/v1/settings/does.not.exist")
        assert resp.status_code == 404


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_unknown_target(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/settings/test-connection",
            json={"target": "unknown_service"},
        )
        assert resp.status_code == 400
