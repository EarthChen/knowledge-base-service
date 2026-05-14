"""IndexTaskManager write-through to SqliteTaskStore."""

from __future__ import annotations

import asyncio
import json

import pytest

from indexer.task_manager import IndexTaskManager
from store.task_store import SqliteTaskStore


@pytest.mark.asyncio
async def test_create_persists_to_sqlite(tmp_path) -> None:
    db_path = str(tmp_path / "idx_mgr.db")
    store = SqliteTaskStore(db_path=db_path)
    await store.initialize()
    mgr = IndexTaskManager(task_store=store)
    task = mgr.create_task(mode="full", directory="/tmp", repository="r1", business_id="default")
    for _ in range(50):
        await asyncio.sleep(0.01)
        row = await store.get(task.task_id)
        if row is not None and row.task_type == "index":
            assert row.status == "pending"
            prog = json.loads(row.progress_json)
            assert prog.get("repository") == "r1"
            await store.close()
            return
    await store.close()
    pytest.fail("index task did not persist")
