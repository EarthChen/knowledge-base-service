"""Unit tests for WikiTaskStore (Redis Hash–backed task CRUD)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

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
    r.eval = AsyncMock(return_value=0)
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
    mock_redis.expire.assert_called_once_with(
        "kb:wiki_tasks:t1", WikiTaskStore.DEFAULT_TTL,
    )


@pytest.mark.asyncio
async def test_try_lock_and_unlock(store, mock_redis):
    mock_redis.set.return_value = True
    token = await store.try_lock("biz1")
    assert token is not None
    mock_redis.set.assert_called_once()
    call_kw = mock_redis.set.call_args
    assert call_kw[0][0] == "kb:wiki_gen_lock:biz1"
    assert call_kw[1].get("nx") is True
    stored_val = call_kw[0][1]
    assert stored_val == token

    mock_redis.eval.return_value = 1
    released = await store.unlock("biz1", token)
    assert released is True
    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_try_lock_already_locked(store, mock_redis):
    mock_redis.set.return_value = False
    locked = await store.try_lock("biz1")
    assert locked is None


@pytest.mark.asyncio
async def test_unlock_wrong_token_does_not_release(store, mock_redis):
    mock_redis.set.return_value = True
    token = await store.try_lock("biz1")
    assert token is not None

    mock_redis.eval.return_value = 0
    released = await store.unlock("biz1", "wrong-token")
    assert released is False


@pytest.mark.asyncio
async def test_lock_stale_holder_does_not_delete_new_holder_token() -> None:
    """After lock expiry + re-acquire, old token unlock must not delete the key."""
    kv: dict[str, str] = {}

    class MiniRedis:
        async def set(self, key: str, val: str, nx: bool = False, ex: int | None = None) -> bool:
            if nx and key in kv:
                return False
            kv[key] = val
            return True

        async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
            if kv.get(key) == token:
                del kv[key]
                return 1
            return 0

    store = WikiTaskStore(MiniRedis())
    bid = "biz-expiry"
    lk = store._lock_key(bid)
    t_old = await store.try_lock(bid)
    assert t_old is not None
    assert kv[lk] == t_old
    del kv[lk]
    t_new = await store.try_lock(bid)
    assert t_new is not None and t_new != t_old
    assert await store.unlock(bid, t_old) is False
    assert kv.get(lk) == t_new
    assert await store.unlock(bid, t_new) is True
    assert lk not in kv


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
