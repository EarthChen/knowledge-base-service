"""Global RPM/TPM rate limiter for LLM calls across pipeline stages."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Mapping
from typing import Any

_WINDOW_SEC = 60.0


class GlobalLLMRateLimiter:
    """Global RPM and TPM rate limiter for LLM calls across all pipeline stages."""

    def __init__(self, rpm_limit: int = 0, tpm_limit: int = 0) -> None:
        self._rpm_limit = rpm_limit
        self._tpm_limit = tpm_limit
        self._request_times: deque[float] = deque()
        self._token_log: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - _WINDOW_SEC
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()
        while self._token_log and self._token_log[0][0] <= cutoff:
            self._token_log.popleft()

    async def acquire(self, estimated_tokens: int = 1000) -> None:
        """Wait until rate limits allow another request."""
        if not self._rpm_limit and not self._tpm_limit:
            return

        async with self._lock:
            now = time.monotonic()
            self._prune(now)

            if self._rpm_limit and len(self._request_times) >= self._rpm_limit:
                wait = _WINDOW_SEC - (now - self._request_times[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
                    self._prune(now)

            if self._tpm_limit:
                current_tokens = sum(tokens for _, tokens in self._token_log)
                if current_tokens + estimated_tokens > self._tpm_limit:
                    wait = _WINDOW_SEC - (now - self._token_log[0][0])
                    if wait > 0:
                        await asyncio.sleep(wait)
                        now = time.monotonic()
                        self._prune(now)

            self._request_times.append(now)
            self._token_log.append((now, estimated_tokens))

    def report_actual_tokens(self, tokens: int) -> None:
        """Update the last entry with actual token count."""
        if self._token_log:
            old_time, _ = self._token_log[-1]
            self._token_log[-1] = (old_time, tokens)


async def acquire_llm_quota(
    config: Mapping[str, Any] | None,
    estimated_tokens: int = 1000,
) -> None:
    """Acquire global LLM quota from LangGraph ``configurable`` when present."""
    if not config:
        return
    limiter = config.get("configurable", {}).get("llm_rate_limiter")
    if limiter:
        await limiter.acquire(estimated_tokens)


def create_llm_rate_limiter(*, rpm_limit: int = 0, tpm_limit: int = 0) -> GlobalLLMRateLimiter:
    """Build a limiter from wiki config limits (0 disables each dimension)."""
    return GlobalLLMRateLimiter(rpm_limit=rpm_limit, tpm_limit=tpm_limit)
