"""Protocol-based LLM provider abstraction and gateway adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx

from llm.provider import LLMProvider


class BaseLLMProvider(Protocol):
    """Protocol for all LLM providers."""

    @property
    def provider_name(self) -> str: ...

    @property
    def supports_streaming(self) -> bool: ...

    @property
    def max_context_tokens(self) -> int: ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str: ...

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...

    async def close(self) -> None: ...


class GatewayLLMProviderAdapter:
    """Wraps the existing LLMProvider (gateway/OpenAI-compatible) as BaseLLMProvider."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    @property
    def provider_name(self) -> str:
        return "gateway"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def max_context_tokens(self) -> int:
        return 128000

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        return await self._inner.complete(messages, model=model, temperature=temperature, **kwargs)

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._inner.complete_json(messages, schema, model=model, **kwargs)

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if hasattr(self._inner, "complete_stream"):
            stream = self._inner.complete_stream(messages, **kwargs)
            async for chunk in stream:  # type: ignore[union-attr]
                if chunk:
                    yield chunk
            return
        yield await self.complete(messages, **kwargs)

    async def close(self) -> None:
        await self._inner.close()


class LLMPortBridge:
    """Bridges BaseLLMProvider to wiki's LLMPort protocol."""

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._provider = provider

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return await self._provider.complete(messages, **kwargs)

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        async for chunk in self._provider.complete_stream(messages, **kwargs):
            if chunk:
                yield chunk

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {"model": model}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if extra_params:
            kwargs.update(extra_params)

        return await self._provider.complete(messages, **kwargs)

    async def _collect_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> str:
        """Collect an SSE stream into a string with bridge-level retry."""
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                parts: list[str] = []
                async for chunk in self._provider.complete_stream(
                    messages, **kwargs
                ):
                    if chunk:
                        parts.append(chunk)
                return "".join(parts)
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2**attempt, 10))
        raise last_exc  # type: ignore[misc]

    async def generate_stream(self, prompt: str, system: str = "", **kwargs: Any) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if not getattr(self._provider, "supports_streaming", False):
            return await self.generate(prompt, system)
        return await self._collect_stream(messages, **kwargs)
