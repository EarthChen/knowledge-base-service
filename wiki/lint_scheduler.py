"""Background scheduler for periodic wiki lint runs."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from log import get_logger

log = get_logger(__name__)


class LintScheduler:
    def __init__(
        self,
        lint_service_factory: Callable[[], Awaitable[Any]],
        interval_seconds: float = 21600,
    ) -> None:
        self._factory = lint_service_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

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
                result = await service.run_full_lint()
                log.info("lint_scheduler_completed", result=result)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("lint_scheduler_failed", exc_info=True)
            await asyncio.sleep(self._interval_seconds)
