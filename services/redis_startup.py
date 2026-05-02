"""Redis/FalkorDB startup helpers — retry while the server is still loading its dataset."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from redis.exceptions import BusyLoadingError

from core.log import get_logger

log = get_logger(__name__)


async def run_sync_with_busy_loading_retry[T](
    loop: asyncio.AbstractEventLoop,
    fn: Callable[[], T],
    *,
    max_attempts: int = 10,
    initial_delay: float = 2.0,
) -> T:
    """Run ``fn`` in the default executor; retry on ``BusyLoadingError`` with exponential backoff."""
    delay = initial_delay
    for attempt in range(max_attempts):
        try:
            return await loop.run_in_executor(None, fn)
        except BusyLoadingError:
            if attempt == max_attempts - 1:
                log.error("redis_busy_loading_gave_up", attempts=max_attempts)
                raise
            log.warning(
                "redis_busy_loading_retry",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                sleep_seconds=delay,
            )
            await asyncio.sleep(delay)
            delay *= 2.0


async def await_with_busy_loading_retry[T](
    coro_factory: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 10,
    initial_delay: float = 2.0,
) -> T:
    """Await an async operation; retry on ``BusyLoadingError`` with exponential backoff."""
    delay = initial_delay
    for attempt in range(max_attempts):
        try:
            return await coro_factory()
        except BusyLoadingError:
            if attempt == max_attempts - 1:
                log.error("redis_busy_loading_async_gave_up", attempts=max_attempts)
                raise
            log.warning(
                "redis_busy_loading_async_retry",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                sleep_seconds=delay,
            )
            await asyncio.sleep(delay)
            delay *= 2.0
