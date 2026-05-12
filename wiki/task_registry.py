from __future__ import annotations

import asyncio
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from wiki.task_store import WikiTaskStore

WIKI_TASK_TTL_SEC = 120 * 60


class WikiTaskRegistry:
    """Wiki generation tasks with optional Redis persistence."""

    def __init__(self, task_store: WikiTaskStore | None = None) -> None:
        self._store = task_store
        self.tasks: dict[str, dict[str, Any]] = {}
        self._created: dict[str, float] = {}
        self._async_tasks: dict[str, asyncio.Task[Any]] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        removed = [tid for tid, ts in self._created.items() if now - ts > WIKI_TASK_TTL_SEC]
        for tid in removed:
            self.tasks.pop(tid, None)
            self._created.pop(tid, None)
            self._async_tasks.pop(tid, None)

    def put_task(self, task_id: str, record: dict[str, Any]) -> None:
        if self._store is not None:
            try:
                asyncio.ensure_future(self._store.put_task(task_id, record))
            except RuntimeError:
                pass
        self._prune()
        self.tasks[task_id] = record
        self._created[task_id] = time.monotonic()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        self._prune()
        return self.tasks.get(task_id)

    def set_async_task(self, task_id: str, task: asyncio.Task[Any]) -> None:
        self._async_tasks[task_id] = task

    def cancel_async_task(self, task_id: str) -> bool:
        t = self._async_tasks.pop(task_id, None)
        if t is not None and not t.done():
            t.cancel()
            return True
        return False

    def is_cancelled(self, task_id: str) -> bool:
        rec = self.tasks.get(task_id)
        return rec is not None and rec.get("status") == "cancelled"
