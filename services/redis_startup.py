"""Redis/FalkorDB startup helpers — retry on transient connection errors."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Executor

from redis.exceptions import BusyLoadingError, ConnectionError as RedisConnectionError

from core.log import get_logger

log = get_logger(__name__)

_RETRYABLE_ERRORS = (BusyLoadingError, RedisConnectionError, ConnectionError, OSError)


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


async def run_with_connection_retry[T](
    executor: Executor | None,
    fn: Callable[[], T],
    *,
    max_attempts: int = 5,
    initial_delay: float = 3.0,
    max_delay: float = 30.0,
) -> T:
    """Run *fn* in *executor*; retry on transient Redis/FalkorDB errors.

    Handles both ``BusyLoadingError`` (server restarting) and ``ConnectionError``
    (server crashed / connection dropped) with exponential backoff.
    """
    loop = asyncio.get_running_loop()
    delay = initial_delay
    for attempt in range(max_attempts):
        try:
            return await loop.run_in_executor(executor, fn)
        except _RETRYABLE_ERRORS as exc:
            if attempt == max_attempts - 1:
                log.error(
                    "falkordb_connection_retry_exhausted",
                    attempts=max_attempts,
                    error=str(exc)[:200],
                )
                raise
            log.warning(
                "falkordb_connection_retry",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                sleep_seconds=delay,
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, max_delay)
    raise RuntimeError("unreachable")
