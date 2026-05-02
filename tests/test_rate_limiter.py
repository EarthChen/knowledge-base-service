"""Tests for rate limiter eviction and skip-prefix behavior."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from api.rate_limiter import RateLimiterMiddleware, _Bucket


class TestRateLimiterEviction:
    def test_evict_removes_stale_buckets(self) -> None:
        mw = RateLimiterMiddleware(app=None, rpm=10)
        now = 1_000_000.0
        mw._last_evict = now - RateLimiterMiddleware._EVICT_INTERVAL - 1
        stale = _Bucket(10)
        stale.last_refill = now - RateLimiterMiddleware._EVICT_AGE - 1
        mw._buckets["stale-ip"] = stale
        fresh = _Bucket(10)
        fresh.last_refill = now - 100.0
        mw._buckets["fresh-ip"] = fresh

        mw._evict_stale(now)

        assert "stale-ip" not in mw._buckets
        assert "fresh-ip" in mw._buckets

    def test_evict_skipped_within_interval(self) -> None:
        mw = RateLimiterMiddleware(app=None, rpm=10)
        now = 2_000_000.0
        mw._last_evict = now - 10.0
        stale = _Bucket(10)
        stale.last_refill = now - RateLimiterMiddleware._EVICT_AGE - 100
        mw._buckets["would-be-stale"] = stale

        mw._evict_stale(now)

        assert "would-be-stale" in mw._buckets


class TestRateLimiterHooksNotSkipped:
    def test_hooks_prefix_not_excluded(self) -> None:
        assert "/api/v1/hooks/" not in RateLimiterMiddleware._SKIP_PREFIXES


@pytest.mark.asyncio
async def test_hooks_path_subject_to_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under RPM budget, hooks routes consume tokens like other API paths."""

    calls: list[int] = []

    async def call_next(_request: Request) -> object:
        calls.append(1)
        return object()

    mw = RateLimiterMiddleware(app=None, rpm=2, trust_proxy=False)

    scope_base = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "method": "POST",
        "path": "/api/v1/hooks/some-hook",
        "raw_path": b"/api/v1/hooks/some-hook",
        "root_path": "",
        "headers": [],
        "client": ("203.0.113.9", 12345),
        "server": ("test", 80),
    }

    req = Request(scope_base)
    await mw.dispatch(req, call_next)
    await mw.dispatch(req, call_next)
    resp = await mw.dispatch(req, call_next)

    assert len(calls) == 2
    assert getattr(resp, "status_code", None) == 429
