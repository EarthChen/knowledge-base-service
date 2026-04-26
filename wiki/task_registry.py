from __future__ import annotations

import time
from typing import Any

WIKI_TASK_TTL_SEC = 30 * 60


class WikiTaskRegistry:
    """In-memory wiki generation tasks. Entries expire after WIKI_TASK_TTL_SEC for bounded memory use."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self._created: dict[str, float] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        removed = [tid for tid, ts in self._created.items() if now - ts > WIKI_TASK_TTL_SEC]
        for tid in removed:
            self.tasks.pop(tid, None)
            self._created.pop(tid, None)

    def put_task(self, task_id: str, record: dict[str, Any]) -> None:
        self._prune()
        self.tasks[task_id] = record
        self._created[task_id] = time.monotonic()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        self._prune()
        return self.tasks.get(task_id)
