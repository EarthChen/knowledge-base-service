"""Unified retry decorator for LLM HTTP providers."""

from __future__ import annotations

import asyncio
import functools
import random
import time as _time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

import httpx

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUSES = {400, 401, 403, 404, 422}

T = TypeVar("T")


def llm_retry(
    max_retries: int = 3,
    max_total_time: float = 90.0,
    respect_retry_after: bool = True,
):
    """Retry decorator for LLM API calls with 429-aware backoff and jitter."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            return await _execute_with_llm_retry(
                lambda: fn(*args, **kwargs),
                max_retries=max_retries,
                max_total_time=max_total_time,
                respect_retry_after=respect_retry_after,
            )

        return wrapper  # type: ignore[return-value]

    return decorator


async def _execute_with_llm_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    max_total_time: float,
    respect_retry_after: bool,
) -> T:
    start = _time.monotonic()
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        if _time.monotonic() - start > max_total_time:
            break
        try:
            return await coro_factory()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in NON_RETRYABLE_STATUSES:
                raise
            last_exc = exc
            if attempt == max_retries:
                break
            wait = _compute_backoff(exc, attempt, respect_retry_after)
            await asyncio.sleep(wait)
        except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            await asyncio.sleep(min(2**attempt + random.uniform(0, 1), 10))
    if last_exc is None:
        raise RuntimeError("llm_retry exhausted without exception")
    raise last_exc


async def llm_retry_async_iterator(
    factory: Callable[[], AsyncIterator[T]],
    *,
    max_retries: int = 3,
    max_total_time: float = 90.0,
    respect_retry_after: bool = True,
) -> AsyncIterator[T]:
    """Retry an async-generator factory on transient LLM errors."""
    start = _time.monotonic()
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        if _time.monotonic() - start > max_total_time:
            break
        try:
            async for item in factory():
                yield item
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in NON_RETRYABLE_STATUSES:
                raise
            last_exc = exc
            if attempt == max_retries:
                break
            wait = _compute_backoff(exc, attempt, respect_retry_after)
            await asyncio.sleep(wait)
        except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            await asyncio.sleep(min(2**attempt + random.uniform(0, 1), 10))
    if last_exc is None:
        raise RuntimeError("llm_retry_async_iterator exhausted without exception")
    raise last_exc


def _compute_backoff(exc: httpx.HTTPStatusError, attempt: int, respect_retry_after: bool) -> float:
    if respect_retry_after and exc.response.status_code == 429:
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60)
            except ValueError:
                pass
    return min(2**attempt + random.uniform(0, 1), 10)
