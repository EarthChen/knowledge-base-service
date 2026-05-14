import asyncio
import json

import pytest

from store.task_store import SqliteTaskStore, TaskRecord


@pytest.fixture
async def store(tmp_path):
    s = SqliteTaskStore(db_path=str(tmp_path / "test_tasks.db"), ttl_seconds=60)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_put_and_get(store):
    rec = TaskRecord(task_id="t1", task_type="wiki_generate", business_id="biz1")
    await store.put(rec)
    loaded = await store.get("t1")
    assert loaded is not None
    assert loaded.task_id == "t1"
    assert loaded.task_type == "wiki_generate"
    assert loaded.status == "pending"


@pytest.mark.asyncio
async def test_get_nonexistent(store):
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_update_status(store):
    await store.put(TaskRecord(task_id="t2", task_type="index"))
    await store.update_status("t2", "running")
    loaded = await store.get("t2")
    assert loaded.status == "running"


@pytest.mark.asyncio
async def test_update_progress(store):
    await store.put(TaskRecord(task_id="t3", task_type="wiki_edit"))
    await store.update_progress("t3", {"step": 2, "total": 5})
    loaded = await store.get("t3")
    progress = json.loads(loaded.progress_json)
    assert progress["step"] == 2


@pytest.mark.asyncio
async def test_list_active(store):
    await store.put(TaskRecord(task_id="a1", task_type="wiki_generate", status="running"))
    await store.put(TaskRecord(task_id="a2", task_type="index", status="pending"))
    await store.put(TaskRecord(task_id="a3", task_type="wiki_generate", status="completed"))
    active = await store.list_active()
    assert len(active) == 2
    active_wiki = await store.list_active(task_type="wiki_generate")
    assert len(active_wiki) == 1


@pytest.mark.asyncio
async def test_try_lock_and_unlock(store):
    token = await store.try_lock("res1", ttl=60)
    assert token is not None
    token2 = await store.try_lock("res1", ttl=60)
    assert token2 is None
    assert await store.unlock("res1", token)
    token3 = await store.try_lock("res1", ttl=60)
    assert token3 is not None


@pytest.mark.asyncio
async def test_lock_expires(tmp_path):
    store = SqliteTaskStore(db_path=str(tmp_path / "lock.db"))
    await store.initialize()
    token = await store.try_lock("res2", ttl=1)
    assert token is not None
    await asyncio.sleep(1.5)
    token2 = await store.try_lock("res2", ttl=60)
    assert token2 is not None
    await store.close()


@pytest.mark.asyncio
async def test_cleanup_expired(tmp_path):
    store = SqliteTaskStore(db_path=str(tmp_path / "cleanup.db"), ttl_seconds=1)
    await store.initialize()
    await store.put(TaskRecord(task_id="old", task_type="x", status="completed"))
    await asyncio.sleep(1.5)
    count = await store.cleanup_expired()
    assert count >= 1
    await store.close()


@pytest.mark.asyncio
async def test_force_release_lock_removes_lock(store):
    token = await store.try_lock("res1", 60)
    assert token is not None
    await store.force_release_lock("res1")
    new_token = await store.try_lock("res1", 60)
    assert new_token is not None


@pytest.mark.asyncio
async def test_list_all_includes_terminal(store):
    await store.put(TaskRecord(task_id="done", task_type="wiki_generate", status="completed"))
    await store.put(TaskRecord(task_id="live", task_type="wiki_generate", status="running"))
    await store.put(TaskRecord(task_id="idx", task_type="index", status="failed"))

    all_rows = await store.list_all(limit=50)
    ids = {r.task_id for r in all_rows}
    assert {"done", "live", "idx"}.issubset(ids)

    wiki_only = await store.list_all(task_type="wiki_generate", limit=50)
    wiki_ids = {r.task_id for r in wiki_only}
    assert "idx" not in wiki_ids
    assert {"done", "live"}.issubset(wiki_ids)
