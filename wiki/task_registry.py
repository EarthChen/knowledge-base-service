from __future__ import annotations

import asyncio
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from wiki.task_store import WikiTaskStore

WIKI_TASK_TTL_SEC = 30 * 60


class WikiTaskRegistry:
    """Wiki generation tasks with optional Redis persistence."""

    def __init__(self, task_store: WikiTaskStore | None = None) -> None:
        self._store = task_store
        self.tasks: dict[str, dict[str, Any]] = {}
        self._created: dict[str, float] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        removed = [tid for tid, ts in self._created.items() if now - ts > WIKI_TASK_TTL_SEC]
        for tid in removed:
            self.tasks.pop(tid, None)
            self._created.pop(tid, None)

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
