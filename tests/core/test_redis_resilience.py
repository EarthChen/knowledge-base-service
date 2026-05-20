"""Tests for Redis retry decorator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from core.redis_resilience import with_redis_retry


class TestWithRedisRetry:
    def test_sync_succeeds_after_transient_connection_error(self) -> None:
        calls = {"n": 0}

        @with_redis_retry(max_retries=3, backoff_base=0.01)
        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 2:
                raise ConnectionError("redis down")
            return "ok"

        with patch("core.redis_resilience.time.sleep"):
            assert flaky() == "ok"
        assert calls["n"] == 2

    def test_sync_gives_up_after_max_retries(self) -> None:
        @with_redis_retry(max_retries=2, backoff_base=0.01)
        def always_fails() -> None:
            raise RedisConnectionError("redis down")

        with patch("core.redis_resilience.time.sleep"):
            with pytest.raises(RedisConnectionError):
                always_fails()

    @pytest.mark.asyncio
    async def test_async_succeeds_after_transient_connection_error(self) -> None:
        calls = {"n": 0}

        @with_redis_retry(max_retries=3, backoff_base=0.01)
        async def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("connection reset")
            return "async-ok"

        with patch("core.redis_resilience.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            assert await flaky() == "async-ok"
        assert calls["n"] == 3
        assert mock_sleep.await_count == 2

    @pytest.mark.asyncio
    async def test_async_gives_up_after_max_retries(self) -> None:
        @with_redis_retry(max_retries=2, backoff_base=0.01)
        async def always_fails() -> None:
            raise RedisConnectionError("redis down")

        with patch("core.redis_resilience.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RedisConnectionError):
                await always_fails()


class TestBusinessManagerRedisRetry:
    def test_list_businesses_retries_on_connection_error(self) -> None:
        from store.business_manager import BusinessManager

        conn = MagicMock()
        conn.scan_iter.side_effect = [ConnectionError("down"), iter([])]
        bm = BusinessManager(MagicMock(connection=conn))

        with patch("core.redis_resilience.time.sleep"):
            assert bm.list_businesses() == []
        assert conn.scan_iter.call_count == 2
