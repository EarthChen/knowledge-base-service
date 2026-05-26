from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Unified LLM domain port.

    Merges the former wiki.context.LLMPort (generate) and
    wiki.ask.LLMPort (complete) into a single protocol.
    All wiki/rag/ask/research services use this protocol.
    """

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str: ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str: ...

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...
