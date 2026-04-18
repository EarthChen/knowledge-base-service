"""Direct OpenAI API provider."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """Direct OpenAI API provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = "https://api.openai.com/v1",
        max_concurrent: int = 10,
        timeout: int = 30,
        retry_count: int = 3,
        temperature: float = 0.1,
        max_context_tokens: int = 128000,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._max_concurrent = max_concurrent
        self._timeout = timeout
        self._retry_count = retry_count
        self._temperature = temperature
        self._max_context_tokens = max_context_tokens
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout),
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def max_context_tokens(self) -> int:
        return self._max_context_tokens

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        body: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
            **kwargs,
        }
        data = await self._request_json(body)
        return data["choices"][0]["message"]["content"]

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _ = schema
        body: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
            **kwargs,
        }
        data = await self._request_json(body)
        raw = data["choices"][0]["message"]["content"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM returned invalid JSON (truncated)", exc_info=True)
            raise ValueError("LLM returned invalid JSON") from exc

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        model = kwargs.pop("model", None)
        temperature = kwargs.pop("temperature", None)
        body: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
            "stream": True,
            **kwargs,
        }
        max_attempts = self._retry_count
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                async with self._semaphore:
                    async with self._client.stream("POST", "/chat/completions", json=body) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line.removeprefix("data: ").strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = (choices[0].get("delta") or {}) if isinstance(choices[0], dict) else {}
                            content = delta.get("content")
                            if content:
                                yield content
                return
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    wait = min(2**attempt, 10)
                    logger.warning(
                        "OpenAI stream failed (attempt %d/%d), retrying in %ds",
                        attempt + 1,
                        max_attempts,
                        wait,
                    )
                    await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

    async def _request_json(self, body: dict[str, Any]) -> dict[str, Any]:
        max_attempts = self._retry_count
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
                        "OpenAI request failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        max_attempts,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

    async def close(self) -> None:
        await self._client.aclose()
