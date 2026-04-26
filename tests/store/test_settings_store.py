"""Tests for SQLite-backed settings store."""

from __future__ import annotations

import asyncio

import pytest

from store.settings_store import SettingsStore


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "kb_settings.db")


@pytest.mark.asyncio
async def test_init_creates_db(db_path):
    SettingsStore(db_path=db_path)
    assert SettingsStore(db_path=db_path) is not None


@pytest.mark.asyncio
async def test_upsert_and_get(db_path):
    store = SettingsStore(db_path=db_path)
    await store.upsert("foo", "bar", "system")
    assert await store.get("foo") == "bar"


@pytest.mark.asyncio
async def test_get_all_grouped_by_category(db_path):
    store = SettingsStore(db_path=db_path)
    await store.upsert("a", "1", "system")
    await store.upsert("b", "2", "llm")
    all_rows = await store.get_all()
    assert all_rows == {"system": {"a": "1"}, "llm": {"b": "2"}}


@pytest.mark.asyncio
async def test_get_by_category(db_path):
    store = SettingsStore(db_path=db_path)
    await store.upsert("x", "y", "embedding")
    assert await store.get_by_category("embedding") == {"x": "y"}
    assert await store.get_by_category("missing") == {}


@pytest.mark.asyncio
async def test_upsert_batch(db_path):
    store = SettingsStore(db_path=db_path)
    await store.upsert_batch(
        [
            {"key": "k1", "value": "v1", "category": "system"},
            {"key": "k2", "value": "v2", "category": "system"},
        ]
    )
    assert await store.get("k1") == "v1"
    assert await store.get("k2") == "v2"


@pytest.mark.asyncio
async def test_delete(db_path):
    store = SettingsStore(db_path=db_path)
    await store.upsert("delme", "x", "system")
    assert await store.delete("delme") is True
    assert await store.get("delme") is None
    assert await store.delete("delme") is False


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(db_path):
    store = SettingsStore(db_path=db_path)
    assert await store.get("nope") is None


def test_get_all_sync(db_path):
    store = SettingsStore(db_path=db_path)

    async def setup() -> None:
        await store.upsert("sync_k", "sync_v", "system")

    asyncio.run(setup())
    assert store.get_all_sync() == {"system": {"sync_k": "sync_v"}}
