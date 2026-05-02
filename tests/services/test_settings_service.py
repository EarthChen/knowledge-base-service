"""Tests for SettingsService merge, masking, and persistence."""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

import services.settings_crypto as settings_crypto
import services.settings_service as settings_service_module
from core.config import LLMConfig, Settings, get_settings
from store.settings_store import SettingsStore


@pytest.fixture(autouse=True)
def clear_get_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reload_crypto_stack(monkeypatch) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)
    importlib.reload(settings_crypto)
    importlib.reload(settings_service_module)


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "kb_settings.db")


@pytest.fixture
def settings_store(db_path) -> SettingsStore:
    return SettingsStore(db_path=db_path)


@pytest.fixture
def settings_service(settings_store) -> settings_service_module.SettingsService:
    return settings_service_module.SettingsService(settings_store)


@pytest.mark.asyncio
async def test_get_all_merged_defaults(settings_service):
    merged = await settings_service.get_all_merged()
    assert "system" in merged
    assert "host" in merged["system"]
    entry = merged["system"]["host"]
    assert entry["source"] == "default"
    assert entry["sensitive"] is False
    assert entry["value"]


@pytest.mark.asyncio
async def test_get_all_merged_with_db_override(settings_service, settings_store):
    await settings_store.upsert("host", "1.2.3.4", "system")
    merged = await settings_service.get_all_merged()
    assert merged["system"]["host"]["value"] == "1.2.3.4"
    assert merged["system"]["host"]["source"] == "db"


@pytest.mark.asyncio
async def test_sensitive_values_masked(settings_service):
    custom = Settings(_env_file=None, llm=LLMConfig(api_key="very-long-secret-key-xyz"))

    with patch.object(settings_service_module, "get_settings", return_value=custom):
        merged = await settings_service.get_all_merged()
    entry = merged["llm"]["llm.api_key"]
    assert entry["sensitive"] is True
    assert entry["source"] == "default"
    assert "***" in entry["value"]
    assert "very-long-secret-key-xyz" not in entry["value"]


@pytest.mark.asyncio
async def test_update_encrypts_sensitive(settings_service, settings_store):
    await settings_service.update_settings(
        [{"key": "llm.api_key", "value": "plain-secret", "category": "llm"}]
    )
    raw = await settings_store.get("llm.api_key")
    assert raw is not None
    assert raw != "plain-secret"
    assert settings_crypto.decrypt_value(raw) == "plain-secret"


@pytest.mark.asyncio
async def test_delete_setting(settings_service, settings_store):
    await settings_store.upsert("host", "9.9.9.9", "system")
    assert await settings_service.delete_setting("host") is True
    merged = await settings_service.get_all_merged()
    assert merged["system"]["host"]["source"] == "default"


@pytest.mark.asyncio
async def test_get_category(settings_service):
    merged = await settings_service.get_all_merged()
    system_cat = await settings_service.get_category("system")
    assert system_cat == merged.get("system", {})


@pytest.mark.asyncio
async def test_update_unknown_key_raises(settings_service):
    with pytest.raises(ValueError, match="Unknown setting key"):
        await settings_service.update_settings(
            [{"key": "invalid.key.xyz", "value": "v", "category": "system"}],
        )
