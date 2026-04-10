"""OpenAI-compatible LLM provider with retry and concurrency control."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from config import LLMConfig

logger = logging.getLogger(__name__)


class LLMProvider:
    """Unified LLM provider supporting OpenAI API and acp-gateway.

    When using acp-gateway as LLM backend, configure base_url to the gateway's
    OpenAI-compatible endpoint. The provider reuses a single httpx client session
    to maintain task affinity with the gateway.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(config.timeout),
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        body: dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._config.temperature,
            **kwargs,
        }
        data = await self._request(body)
        return data["choices"][0]["message"]["content"]

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "response_format": {"type": "json_object"},
            **kwargs,
        }
        data = await self._request(body)
        raw = data["choices"][0]["message"]["content"]
        return json.loads(raw)

    async def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        max_attempts = self._config.retry_count
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                async with self._semaphore:
                    resp = await self._client.post("/chat/completions", json=body)
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    wait = min(2**attempt, 10)
                    logger.warning(
                        "LLM request failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        max_attempts,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

    async def close(self) -> None:
        await self._client.aclose()
