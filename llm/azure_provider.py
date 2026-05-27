"""Azure OpenAI API provider."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from llm.retry import llm_retry, llm_retry_async_iterator

logger = logging.getLogger(__name__)


class AzureOpenAIProvider:
    """Azure OpenAI API provider."""

    def __init__(
        self,
        api_key: str,
        resource_name: str,
        deployment_name: str,
        api_version: str = "2024-02-15-preview",
        max_concurrent: int = 10,
        timeout: int = 30,
        retry_count: int = 3,
        temperature: float = 0.1,
        max_context_tokens: int = 128000,
    ) -> None:
        self._api_key = api_key
        self._resource_name = resource_name
        self._deployment_name = deployment_name
        self._api_version = api_version
        self._max_concurrent = max_concurrent
        self._timeout = timeout
        self._retry_count = retry_count
        self._temperature = temperature
        self._max_context_tokens = max_context_tokens
        self._base_url = (
            f"https://{resource_name}.openai.azure.com/openai/deployments/{deployment_name}"
        )
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"api-key": api_key},
            timeout=httpx.Timeout(timeout),
        )

    @property
    def provider_name(self) -> str:
        return "azure"

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
        _ = model
        body: dict[str, Any] = {
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
        if schema:
            from llm.provider import normalize_schema_for_strict

            normalized = normalize_schema_for_strict(schema)
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": normalized.get("title", "output"),
                    "strict": True,
                    "schema": normalized,
                },
            }
        else:
            logger.warning("complete_json called without schema — falling back to json_object")
            response_format = {"type": "json_object"}
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": self._temperature,
            "response_format": response_format,
            **kwargs,
        }
        data = await self._request_json(body)
        raw = data["choices"][0]["message"]["content"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Azure OpenAI returned invalid JSON", exc_info=True)
            raise ValueError("LLM returned invalid JSON") from exc

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        temperature = kwargs.pop("temperature", None)
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
            "stream": True,
            **kwargs,
        }
        params = {"api-version": self._api_version}

        async def stream_once() -> AsyncIterator[str]:
            async with self._semaphore:
                async with self._client.stream(
                    "POST",
                    "/chat/completions",
                    json=body,
                    params=params,
                ) as resp:
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

        async for chunk in llm_retry_async_iterator(stream_once, max_retries=self._retry_count):
            yield chunk

    async def _request_json(self, body: dict[str, Any]) -> dict[str, Any]:
        params = {"api-version": self._api_version}

        @llm_retry(max_retries=self._retry_count)
        async def _call() -> dict[str, Any]:
            async with self._semaphore:
                resp = await self._client.post("/chat/completions", json=body, params=params)
                resp.raise_for_status()
                return resp.json()

        return await _call()

    async def close(self) -> None:
        await self._client.aclose()
