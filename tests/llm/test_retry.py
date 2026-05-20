"""Tests for unified LLM retry decorator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from llm.retry import _compute_backoff, llm_retry


class TestLlmRetry:
    @pytest.mark.asyncio
    async def test_retries_on_500_then_succeeds(self) -> None:
        calls = {"n": 0}

        @llm_retry(max_retries=3, max_total_time=90.0)
        async def call_api() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                response = MagicMock()
                response.status_code = 500
                request = MagicMock()
                raise httpx.HTTPStatusError("err", request=request, response=response)
            return "ok"

        with patch("llm.retry.asyncio.sleep", new_callable=AsyncMock):
            assert await call_api() == "ok"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self) -> None:
        @llm_retry(max_retries=3)
        async def call_api() -> str:
            response = MagicMock()
            response.status_code = 400
            request = MagicMock()
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await call_api()
        assert exc_info.value.response.status_code == 400

    @pytest.mark.asyncio
    async def test_429_respects_retry_after_header(self) -> None:
        calls = {"n": 0}
        sleep_args: list[float] = []

        @llm_retry(max_retries=2, respect_retry_after=True)
        async def call_api() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                response = MagicMock()
                response.status_code = 429
                response.headers = {"Retry-After": "5"}
                request = MagicMock()
                raise httpx.HTTPStatusError("rate limited", request=request, response=response)
            return "ok"

        async def capture_sleep(delay: float) -> None:
            sleep_args.append(delay)

        with patch("llm.retry.asyncio.sleep", side_effect=capture_sleep):
            assert await call_api() == "ok"
        assert sleep_args == [5.0]

    @pytest.mark.asyncio
    async def test_max_total_time_cap(self) -> None:
        @llm_retry(max_retries=100, max_total_time=0.05)
        async def call_api() -> str:
            response = MagicMock()
            response.status_code = 503
            request = MagicMock()
            raise httpx.HTTPStatusError("unavailable", request=request, response=response)

        with patch("llm.retry.asyncio.sleep", new_callable=AsyncMock):
            with patch("llm.retry._time.monotonic", side_effect=[0.0, 0.0, 0.2]):
                with pytest.raises(httpx.HTTPStatusError):
                    await call_api()

    def test_compute_backoff_uses_jitter_when_not_429(self) -> None:
        exc = MagicMock()
        exc.response.status_code = 500
        with patch("llm.retry.random.uniform", return_value=0.5):
            assert _compute_backoff(exc, attempt=2, respect_retry_after=True) == pytest.approx(4.5)

    def test_backoff_not_deterministic_without_patch(self) -> None:
        exc = MagicMock()
        exc.response.status_code = 500
        values = {_compute_backoff(exc, attempt=1, respect_retry_after=True) for _ in range(20)}
        assert len(values) > 1
