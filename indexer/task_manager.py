"""Background index task management with progress tracking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from log import get_logger

log = get_logger(__name__)


@dataclass
class IndexProgress:
    phase: str = "scanning"
    total_files: int = 0
    processed_files: int = 0
    current_file: str = ""
    stats: dict[str, int] = field(default_factory=dict)
    # LLM enrichment: "gateway" (ACP 网关) | "direct" (直连 LLM) | "" (未启用)
    enrichment_backend: str = ""
    enriched_count: int = 0


@dataclass
class IndexTask:
    task_id: str
    status: str = "pending"
    mode: str = "full"
    directory: str = ""
    repository: str | None = None
    business_id: str = "default"
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    progress: IndexProgress = field(default_factory=IndexProgress)
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "mode": self.mode,
            "directory": self.directory,
            "repository": self.repository,
            "business_id": self.business_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": {
                "phase": self.progress.phase,
                "total_files": self.progress.total_files,
                "processed_files": self.progress.processed_files,
                "current_file": self.progress.current_file,
                "stats": dict(self.progress.stats),
                "enrichment_backend": self.progress.enrichment_backend,
                "enriched_count": self.progress.enriched_count,
            },
            "result": self.result,
            "error": self.error,
        }


ProgressCallback = Callable[..., None]


class IndexTaskManager:
    """Manages background indexing tasks with progress tracking."""

    def __init__(self) -> None:
        self._tasks: dict[str, IndexTask] = {}
        self._max_history = 50

    def create_task(
        self, mode: str, directory: str, repository: str | None, business_id: str,
    ) -> IndexTask:
        task_id = uuid.uuid4().hex[:12]
        task = IndexTask(
            task_id=task_id,
            mode=mode,
            directory=directory,
            repository=repository,
            business_id=business_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._tasks[task_id] = task
        self._cleanup_old_tasks()
        return task

    def get_task(self, task_id: str) -> IndexTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[IndexTask]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def make_progress_callback(self, task_id: str) -> ProgressCallback:
        def callback(
            phase: str = "",
            current_file: str = "",
            total_files: int = 0,
            processed_files: int = 0,
            enrichment_backend: str = "",
            enriched_count: int | None = None,
            **stats: int,
        ) -> None:
            task = self._tasks.get(task_id)
            if not task:
                return
            if phase:
                task.progress.phase = phase
            if current_file:
                task.progress.current_file = current_file
            if total_files > 0:
                task.progress.total_files = total_files
            if processed_files > 0:
                task.progress.processed_files = processed_files
            if enrichment_backend:
                task.progress.enrichment_backend = enrichment_backend
            if enriched_count is not None:
                task.progress.enriched_count = enriched_count
            if stats:
                task.progress.stats.update(stats)
        return callback

    def mark_running(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = "running"
            task.started_at = datetime.now(timezone.utc).isoformat()

    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.result = result
            task.progress.phase = "completed"

    def mark_failed(self, task_id: str, error: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = "failed"
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.error = error

    def _cleanup_old_tasks(self) -> None:
        if len(self._tasks) <= self._max_history:
            return
        completed = [
            (tid, t) for tid, t in self._tasks.items()
            if t.status in ("completed", "failed")
        ]
        completed.sort(key=lambda x: x[1].created_at)
        while len(self._tasks) > self._max_history and completed:
            tid, _ = completed.pop(0)
            del self._tasks[tid]
