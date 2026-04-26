"""Background scheduler for periodic wiki lint runs."""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from log import get_logger

log = get_logger(__name__)


class LintScheduler:
    def __init__(
        self,
        lint_service_factory: Callable[[], Awaitable[Any]],
        repositories: list[str] | Callable[[], Awaitable[list[str]] | list[str]],
        *,
        interval_seconds: float = 21600,
    ) -> None:
        self._factory = lint_service_factory
        self._repositories = repositories
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def _resolve_repositories(self) -> list[str]:
        r = self._repositories
        if isinstance(r, list):
            return r
        out = r()
        if inspect.isawaitable(out):
            resolved = await out
        else:
            resolved = out
        return list(resolved) if resolved else []

    def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                service = await self._factory()
                repos = await self._resolve_repositories()
                for repo in repos:
                    result = await service.lint(repo)
                    log.info(
                        "lint_scheduler_repo_completed",
                        repository=repo,
                        issues=len(result.issues) if result is not None else 0,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("lint_scheduler_failed", exc_info=True)
            await asyncio.sleep(self._interval_seconds)
