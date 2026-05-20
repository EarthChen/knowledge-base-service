"""OpenAI-compatible LLM provider with retry and concurrency control."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core.config import LLMConfig
from llm.retry import llm_retry, llm_retry_async_iterator

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

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """OpenAI-style SSE stream; yields text content deltas."""
        body: dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "stream": True,
            **kwargs,
        }
        async def stream_once() -> AsyncIterator[str]:
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
                            yield str(content)

        async for chunk in llm_retry_async_iterator(
            stream_once,
            max_retries=self._config.retry_count,
        ):
            yield chunk

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
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM returned invalid JSON: %s", raw[:200], exc_info=True)
            raise ValueError(f"LLM returned invalid JSON: {raw[:100]}") from exc

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """OpenAI-compatible tool-calling request."""
        body: dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "tools": tools,
            "temperature": self._config.temperature,
            **kwargs,
        }
        data = await self._request(body)
        return data["choices"][0]["message"]

    async def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        @llm_retry(max_retries=self._config.retry_count)
        async def _call() -> dict[str, Any]:
            async with self._semaphore:
                resp = await self._client.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()

        return await _call()

    async def close(self) -> None:
        await self._client.aclose()
