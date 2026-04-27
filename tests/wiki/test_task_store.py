"""Unit tests for WikiTaskStore (Redis Hash–backed task CRUD)."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.task_store import WikiTaskStore


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.hset = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.expire = AsyncMock()
    r.delete = AsyncMock()
    r.scan = AsyncMock(return_value=(0, []))
    r.exists = AsyncMock(return_value=0)
    r.set = AsyncMock(return_value=True)
    return r


@pytest.fixture
def store(mock_redis):
    return WikiTaskStore(mock_redis)


@pytest.mark.asyncio
async def test_put_and_get_task(store, mock_redis):
    record = {"task_id": "t1", "status": "pending", "business_id": "biz"}
    await store.put_task("t1", record)
    mock_redis.hset.assert_called_once()
    call_kwargs = mock_redis.hset.call_args
    assert call_kwargs[0][0] == "kb:wiki_tasks:t1"
    mock_redis.expire.assert_called_once_with("kb:wiki_tasks:t1", WikiTaskStore.DEFAULT_TTL)

    mock_redis.hgetall.return_value = {
        b"task_id": b"t1", b"status": b"pending", b"business_id": b"biz",
    }
    result = await store.get_task("t1")
    assert result is not None
    assert result["task_id"] == "t1"
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_get_task_not_found(store, mock_redis):
    mock_redis.hgetall.return_value = {}
    result = await store.get_task("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_update_status(store, mock_redis):
    await store.update_status("t1", "running", current_repo="user-svc")
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "kb:wiki_tasks:t1"
    mapping = call_args[1].get("mapping") or call_args[0][1]
    assert mapping["status"] == "running"
    assert mapping["current_repo"] == "user-svc"


@pytest.mark.asyncio
async def test_try_lock_and_unlock(store, mock_redis):
    mock_redis.set.return_value = True
    locked = await store.try_lock("biz1")
    assert locked is True
    mock_redis.set.assert_called_once()

    await store.unlock("biz1")
    mock_redis.delete.assert_called_once_with("kb:wiki_gen_lock:biz1")


@pytest.mark.asyncio
async def test_try_lock_already_locked(store, mock_redis):
    mock_redis.set.return_value = False
    locked = await store.try_lock("biz1")
    assert locked is False


@pytest.mark.asyncio
async def test_list_active_empty(store, mock_redis):
    mock_redis.scan.return_value = (0, [])
    result = await store.list_active()
    assert result == []


@pytest.mark.asyncio
async def test_task_registry_delegates_to_store(mock_redis):
    """When WikiTaskStore is injected, WikiTaskRegistry delegates get/put."""
    from wiki.task_registry import WikiTaskRegistry

    store = WikiTaskStore(mock_redis)
    registry = WikiTaskRegistry(task_store=store)

    mock_redis.hgetall.return_value = {
        b"task_id": b"t1", b"status": b"pending",
    }
    registry.put_task("t1", {"task_id": "t1", "status": "pending"})
    result = registry.get_task("t1")
    assert result is not None
    assert result["task_id"] == "t1"


def test_task_registry_works_without_store():
    """Backward compat: no store → in-memory dict."""
    from wiki.task_registry import WikiTaskRegistry

    registry = WikiTaskRegistry()
    registry.put_task("t1", {"task_id": "t1", "status": "pending"})
    assert registry.get_task("t1")["status"] == "pending"
