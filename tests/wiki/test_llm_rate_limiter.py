"""Unit tests for GlobalLLMRateLimiter."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from wiki.llm_rate_limiter import GlobalLLMRateLimiter


@pytest.mark.asyncio
async def test_disabled_limiter_returns_immediately() -> None:
    limiter = GlobalLLMRateLimiter(rpm_limit=0, tpm_limit=0)
    await limiter.acquire()
    await limiter.acquire(estimated_tokens=50_000)


@pytest.mark.asyncio
async def test_rpm_limiting_waits_when_exceeded() -> None:
    limiter = GlobalLLMRateLimiter(rpm_limit=2, tpm_limit=0)
    clock = [0.0]

    async def fake_sleep(duration: float) -> None:
        clock[0] += duration

    with (
        patch("wiki.llm_rate_limiter.time.monotonic", lambda: clock[0]),
        patch("wiki.llm_rate_limiter.asyncio.sleep", fake_sleep),
    ):
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()

    assert clock[0] == 60.0


@pytest.mark.asyncio
async def test_tpm_limiting_waits_when_exceeded() -> None:
    limiter = GlobalLLMRateLimiter(rpm_limit=0, tpm_limit=1000)
    clock = [0.0]

    async def fake_sleep(duration: float) -> None:
        clock[0] += duration

    with (
        patch("wiki.llm_rate_limiter.time.monotonic", lambda: clock[0]),
        patch("wiki.llm_rate_limiter.asyncio.sleep", fake_sleep),
    ):
        await limiter.acquire(estimated_tokens=600)
        await limiter.acquire(estimated_tokens=500)

    assert clock[0] == 60.0


@pytest.mark.asyncio
async def test_report_actual_tokens_updates_last_entry() -> None:
    limiter = GlobalLLMRateLimiter(rpm_limit=0, tpm_limit=10_000)
    await limiter.acquire(estimated_tokens=8000)
    limiter.report_actual_tokens(2000)
    assert sum(tokens for _, tokens in limiter._token_log) == 2000


@pytest.mark.asyncio
async def test_concurrent_acquire_calls_are_serialized() -> None:
    limiter = GlobalLLMRateLimiter(rpm_limit=1, tpm_limit=0)
    clock = [0.0]
    order: list[str] = []

    async def fake_sleep(duration: float) -> None:
        clock[0] += duration

    async def first() -> None:
        order.append("first_start")
        await limiter.acquire()
        order.append("first_done")

    async def second() -> None:
        order.append("second_start")
        await limiter.acquire()
        order.append("second_done")

    with (
        patch("wiki.llm_rate_limiter.time.monotonic", lambda: clock[0]),
        patch("wiki.llm_rate_limiter.asyncio.sleep", fake_sleep),
    ):
        await asyncio.gather(first(), second())

    assert order.index("first_done") < order.index("second_start")
    assert clock[0] == 60.0


@pytest.mark.asyncio
async def test_pruning_removes_entries_older_than_60s() -> None:
    limiter = GlobalLLMRateLimiter(rpm_limit=2, tpm_limit=0)
    clock = [0.0]

    async def fake_sleep(duration: float) -> None:
        clock[0] += duration

    with (
        patch("wiki.llm_rate_limiter.time.monotonic", lambda: clock[0]),
        patch("wiki.llm_rate_limiter.asyncio.sleep", fake_sleep),
    ):
        await limiter.acquire()
        clock[0] = 61.0
        await limiter.acquire()
        await limiter.acquire()

    assert len(limiter._request_times) == 2
    assert clock[0] == 61.0
