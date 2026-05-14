"""WikiTaskRegistry persistence via SqliteTaskStore."""

from __future__ import annotations

import asyncio

import pytest

from store.task_store import SqliteTaskStore
from wiki.task_registry import WikiTaskRegistry


@pytest.mark.asyncio
async def test_put_persists_to_sqlite(tmp_path) -> None:
    db = tmp_path / "reg.db"
    store = SqliteTaskStore(db_path=str(db))
    await store.initialize()
    reg = WikiTaskRegistry(task_store=store)
    reg.put_task(
        "t1",
        {
            "task_id": "t1",
            "task_type": "wiki_generate",
            "status": "pending",
            "business_id": "biz-a",
            "incremental": "true",
        },
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        row = await store.get("t1")
        if row is not None and row.business_id == "biz-a":
            assert row.status == "pending"
            assert row.task_type == "wiki_generate"
            await store.close()
            return
    await store.close()
    pytest.fail("task did not persist to SQLite")
