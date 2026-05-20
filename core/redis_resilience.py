"""Shared retry decorator for Redis operations."""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from typing import TypeVar

from redis.exceptions import BusyLoadingError
from redis.exceptions import ConnectionError as RedisConnectionError

T = TypeVar("T")


def with_redis_retry(max_retries: int = 3, backoff_base: float = 1.0):
    """Retry decorator supporting both sync and async Redis operations."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs) -> T:
                for attempt in range(max_retries):
                    try:
                        return await fn(*args, **kwargs)
                    except (RedisConnectionError, ConnectionError, OSError, BusyLoadingError):
                        if attempt == max_retries - 1:
                            raise
                        await asyncio.sleep(min(backoff_base * 2**attempt, 10))

                raise RuntimeError("unreachable")

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs) -> T:
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except (RedisConnectionError, ConnectionError, OSError, BusyLoadingError):
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(min(backoff_base * 2**attempt, 10))

            raise RuntimeError("unreachable")

        return sync_wrapper  # type: ignore[return-value]

    return decorator
