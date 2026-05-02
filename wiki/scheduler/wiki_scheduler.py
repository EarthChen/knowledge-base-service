"""Interval-based wiki regeneration scheduler with webhook-aware locking."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from core.log import get_logger
from wiki.scheduler.task_lock import TaskLock

log = get_logger(__name__)


@dataclass
class ScheduleConfig:
    schedule_type: str = "none"  # 'none' | 'interval'
    interval_hours: int = 24
    enabled_repositories: list[str] = field(default_factory=list)


@dataclass
class SchedulerStatus:
    repository: str
    schedule_type: str
    interval_hours: int
    last_run: datetime | None
    last_result: str  # 'success' | 'failed' | 'pending'
    next_run: datetime | None


class WikiScheduler:
    """Runs periodic wiki regeneration for enabled repositories."""

    def __init__(
        self,
        config: ScheduleConfig,
        task_lock: TaskLock,
        regenerate_fn: Callable[[str], Awaitable[None]],
        supervisor: Any = None,
    ) -> None:
        self._config = config
        self._task_lock = task_lock
        self._regenerate_fn = regenerate_fn
        self._supervisor = supervisor
        self._loop_task: asyncio.Task[None] | None = None
        self._supervisor_spawn_id: str | None = None
        self._stop_event = asyncio.Event()
        self._repo_last_run: dict[str, datetime | None] = {}
        self._repo_last_result: dict[str, str] = {}
        self._repo_next_run: dict[str, datetime | None] = {}
        self._init_repo_state(list(config.enabled_repositories))

    def _init_repo_state(self, repositories: list[str]) -> None:
        for repo in repositories:
            self._repo_last_run.setdefault(repo, None)
            self._repo_last_result.setdefault(repo, "pending")
            self._repo_next_run.setdefault(repo, None)

    def update_config(self, config: ScheduleConfig) -> None:
        """Replace schedule configuration (picked up by the scheduler loop)."""
        self._config = config
        self._init_repo_state(list(config.enabled_repositories))

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._loop_task is not None and not self._loop_task.done():
            return
        if (
            self._supervisor is not None
            and self._supervisor_spawn_id is not None
            and (ot := self._supervisor.asyncio_task_for(self._supervisor_spawn_id)) is not None
            and not ot.done()
        ):
            return
        self._stop_event.clear()
        if self._supervisor is not None:
            self._supervisor_spawn_id = self._supervisor.spawn(
                lambda: self._run_loop(),
                name="scheduler:wiki",
                max_retries=3,
                retry_delay=10.0,
            )
        else:
            self._loop_task = asyncio.create_task(self._run_loop(), name="wiki-scheduler")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._stop_event.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        elif self._supervisor is not None and self._supervisor_spawn_id:
            ot = self._supervisor.asyncio_task_for(self._supervisor_spawn_id)
            self._supervisor.cancel(self._supervisor_spawn_id)
            if ot is not None:
                try:
                    await ot
                except asyncio.CancelledError:
                    pass
            self._supervisor_spawn_id = None

    async def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                cfg = self._config
                if cfg.schedule_type == "none":
                    await asyncio.sleep(1.0)
                    continue
                if cfg.schedule_type == "interval":
                    interval_sec = float(cfg.interval_hours * 3600)
                    for repo in list(cfg.enabled_repositories):
                        if self._stop_event.is_set():
                            break
                        acquired = await self._task_lock.acquire(repo)
                        if not acquired:
                            self._repo_last_result[repo] = "pending"
                            continue
                        try:
                            await self._regenerate_fn(repo)
                        except Exception:
                            log.exception("wiki scheduler regenerate failed", repository=repo)
                            self._repo_last_result[repo] = "failed"
                            now = datetime.now(tz=UTC)
                            self._repo_last_run[repo] = now
                            self._repo_next_run[repo] = now + timedelta(hours=cfg.interval_hours)
                        else:
                            self._repo_last_result[repo] = "success"
                            now = datetime.now(tz=UTC)
                            self._repo_last_run[repo] = now
                            self._repo_next_run[repo] = now + timedelta(hours=cfg.interval_hours)
                        finally:
                            await self._task_lock.release(repo)
                    await asyncio.sleep(interval_sec)
                else:
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise

    def get_status(self) -> list[SchedulerStatus]:
        """Get status of all scheduled repositories."""
        cfg = self._config
        out: list[SchedulerStatus] = []
        for repo in cfg.enabled_repositories:
            out.append(
                SchedulerStatus(
                    repository=repo,
                    schedule_type=cfg.schedule_type,
                    interval_hours=cfg.interval_hours,
                    last_run=self._repo_last_run.get(repo),
                    last_result=self._repo_last_result.get(repo, "pending"),
                    next_run=self._repo_next_run.get(repo),
                )
            )
        return out
