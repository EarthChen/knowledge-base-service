"""Bridge LangGraph/LangChain events to structlog."""
from __future__ import annotations

from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from log import get_logger

log = get_logger(__name__)


class StructlogCallbackHandler(AsyncCallbackHandler):
    """Emits structlog events for every LLM call in the pipeline."""

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        model_id = serialized.get("id", ["unknown"])
        if isinstance(model_id, list):
            model_name = model_id[-1] if model_id else "unknown"
        else:
            model_name = str(model_id)
        prompt_tokens = sum(len(p) // 3 for p in prompts)
        log.info("llm_call_start", model=model_name, prompt_tokens=prompt_tokens)

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        response_tokens = len(str(response)) // 3
        log.info("llm_call_done", response_tokens=response_tokens)

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        log.error("llm_call_failed", error=str(error)[:200])
