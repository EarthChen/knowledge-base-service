"""LangChain ChatModel adapter for LLMPortBridge."""
from __future__ import annotations

from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class LLMPortChatModel(BaseChatModel):
    """Wraps LLMPortBridge as a LangChain ChatModel.

    The bridge talks to our internal ai-gateway. This adapter lets us use
    LangGraph nodes, with_structured_output, OutputFixingParser, etc.
    """

    bridge: Any
    model_name: str = "default"

    @property
    def _llm_type(self) -> str:
        return "llm-port-bridge"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("Use async via ainvoke / _agenerate")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        lm_messages = _convert_messages(messages)
        model = kwargs.get("model") or self.model_name
        bridge_kwargs: dict[str, Any] = {"model": model}
        if "temperature" in kwargs:
            bridge_kwargs["temperature"] = kwargs["temperature"]
        result = await self.bridge.complete(lm_messages, **bridge_kwargs)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=result))]
        )


def _convert_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = m.type
        if role == "human":
            role = "user"
        content = m.content if isinstance(m.content, str) else str(m.content)
        out.append({"role": role, "content": content})
    return out
