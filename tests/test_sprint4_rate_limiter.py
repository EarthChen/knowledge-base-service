"""Tests for the per-IP rate limiter middleware."""

from __future__ import annotations

import pytest
from api.rate_limiter import RateLimiterMiddleware, _Bucket


class TestBucket:
    def test_initial_tokens(self):
        b = _Bucket(60)
        assert b.tokens == 60.0

    def test_last_refill_set(self):
        b = _Bucket(100)
        assert b.last_refill > 0


class TestRateLimiterMiddleware:
    def test_skip_health(self):
        assert "/health" in RateLimiterMiddleware._SKIP_PATHS

    def test_skip_prefixes(self):
        assert any(p.startswith("/assets") for p in RateLimiterMiddleware._SKIP_PREFIXES)

    def test_zero_rpm_disables(self):
        mw = RateLimiterMiddleware(app=None, rpm=0)
        assert mw._rpm == 0

    def test_bucket_per_ip(self):
        mw = RateLimiterMiddleware(app=None, rpm=10)
        b1 = mw._buckets["1.2.3.4"]
        b2 = mw._buckets["5.6.7.8"]
        assert b1 is not b2
        assert b1.tokens == 10.0


class TestSettingsRateLimitConfig:
    """Ensure rate_limiter config integration works."""

    def test_settings_has_rate_limit_rpm(self):
        from config import Settings
        s = Settings(rate_limit_rpm=60)
        assert s.rate_limit_rpm == 60

    def test_settings_default_rpm(self):
        from config import Settings
        s = Settings()
        assert s.rate_limit_rpm == 120
