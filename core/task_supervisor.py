"""Centralized background task supervision with retry, cancellation, and health reporting."""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_MAX_RETRY_DELAY = 60.0


@dataclass
class _TaskRecord:
    task_id: str
    name: str
    asyncio_task: asyncio.Task[None]
    created_at: float
    retry_count: int = 0
    max_retries: int = 0


class TaskSupervisor:
    """Manages background asyncio tasks with retry, cancellation, and graceful shutdown."""

    def __init__(self) -> None:
        self._tasks: dict[str, _TaskRecord] = {}
        self._shutting_down = False
        self._total_spawned = 0
        self._total_completed = 0
        self._total_failed = 0
        self._total_retried = 0

    def spawn(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, None]],
        *,
        name: str,
        max_retries: int = 0,
        retry_delay: float = 5.0,
        timeout: float | None = None,
        on_failure: Callable[[str, BaseException], None] | None = None,
    ) -> str:
        if self._shutting_down:
            raise RuntimeError("TaskSupervisor is shutting down; cannot spawn new tasks")

        task_id = f"{name}:{uuid.uuid4().hex[:8]}"
        self._total_spawned += 1

        async def _wrapper() -> None:
            retries = 0
            delay = retry_delay
            while True:
                try:
                    coro = coro_factory()
                    if timeout is not None:
                        await asyncio.wait_for(coro, timeout=timeout)
                    else:
                        await coro
                    self._total_completed += 1
                    log.info("task_completed", task_id=task_id, name=name)
                    return
                except asyncio.CancelledError:
                    log.info("task_cancelled", task_id=task_id, name=name)
                    raise
                except Exception as exc:
                    if retries < max_retries:
                        retries += 1
                        self._total_retried += 1
                        if task_id in self._tasks:
                            self._tasks[task_id].retry_count = retries
                        log.warning(
                            "task_retry",
                            task_id=task_id,
                            name=name,
                            attempt=retries,
                            max_retries=max_retries,
                            delay=delay,
                            error=str(exc),
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, _MAX_RETRY_DELAY)
                    else:
                        self._total_failed += 1
                        log.error(
                            "task_failed",
                            task_id=task_id,
                            name=name,
                            retries=retries,
                            error=str(exc),
                            exc_info=True,
                        )
                        if on_failure is not None:
                            try:
                                on_failure(task_id, exc)
                            except Exception:
                                log.warning(
                                    "task_on_failure_callback_error",
                                    task_id=task_id,
                                    exc_info=True,
                                )
                        return

        def _done_cb(t: asyncio.Task[None]) -> None:
            self._tasks.pop(task_id, None)

        atask = asyncio.create_task(_wrapper(), name=task_id)
        atask.add_done_callback(_done_cb)
        self._tasks[task_id] = _TaskRecord(
            task_id=task_id,
            name=name,
            asyncio_task=atask,
            created_at=time.monotonic(),
            max_retries=max_retries,
        )
        log.info("task_spawned", task_id=task_id, name=name)
        return task_id

    def asyncio_task_for(self, task_id: str) -> asyncio.Task[None] | None:
        record = self._tasks.get(task_id)
        return record.asyncio_task if record else None

    def cancel(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if record is None:
            return False
        record.asyncio_task.cancel()
        return True

    async def shutdown(self, timeout: float = 30.0) -> None:
        self._shutting_down = True
        if not self._tasks:
            return
        tasks = [r.asyncio_task for r in self._tasks.values()]
        log.info("task_supervisor_shutdown_start", active=len(tasks), timeout=timeout)
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5.0)
            log.warning("task_supervisor_shutdown_cancelled", count=len(pending))
        log.info("task_supervisor_shutdown_complete")

    @property
    def active_tasks(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        return {
            tid: {
                "name": r.name,
                "created_at": r.created_at,
                "running_for_s": round(now - r.created_at, 1),
                "retry_count": r.retry_count,
                "max_retries": r.max_retries,
            }
            for tid, r in self._tasks.items()
        }

    @property
    def stats(self) -> dict[str, int]:
        return {
            "total_spawned": self._total_spawned,
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
            "total_retried": self._total_retried,
            "active": len(self._tasks),
        }
