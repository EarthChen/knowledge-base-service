from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from wiki.agents.events import (
    EventCallback,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
)

from core.log import get_logger
from wiki.tool_guardrail import DefaultToolGuardrail

log = get_logger(__name__)


@dataclass
class ToolDef:
    """A single tool definition with handler and activation tier."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    tier: int = 1

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Manages tool definitions with tiered progressive activation."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}
        self._guardrail = DefaultToolGuardrail()

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def has_tools(self) -> bool:
        return bool(self._tools)

    def get_all_tool_schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def get_tools_for_round(
        self, round_num: int, has_empty: bool
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for t in self._tools.values():
            if has_empty or t.tier == 1:
                result.append(t.to_openai_schema())
            elif t.tier == 2 and round_num >= 3:
                result.append(t.to_openai_schema())
            elif t.tier == 3 and round_num >= 5:
                result.append(t.to_openai_schema())
        return result

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}

        validated_args = await self._guardrail.pre_call(name, args)
        if validated_args is None:
            return {"error": f"rejected by guardrail: {name} missing required params"}

        try:
            return await tool.handler(validated_args)
        except Exception as exc:
            log.warning("tool_dispatch_error", tool=name, exc_info=True)
            return {"error": str(exc)}


class GenericAgent(ABC):
    """Pure LLM execution engine — no domain knowledge.

    Subclasses must implement incorporate() and memory_to_prompt()
    to define how tool results map to memory and how memory is
    presented to the LLM.
    """

    def __init__(
        self,
        llm: Any,
        *,
        max_rounds: int = 6,
        max_tool_calls: int = 30,
    ) -> None:
        self._llm = llm
        self._tool_registry = ToolRegistry()
        self._max_rounds = max_rounds
        self._max_tool_calls = max_tool_calls

    @abstractmethod
    def incorporate(
        self, tool_name: str, result: dict[str, Any], memory: Any
    ) -> None:
        """Map a tool result into the appropriate memory category."""

    @abstractmethod
    def memory_to_prompt(self, memory: Any) -> str:
        """Format memory contents as a prompt section for the LLM."""

    def _summarize_tool_result(self, result: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False, default=str)[:200]

    def create_memory(self) -> Any:
        """Factory method. Override in subclasses for specialized memory."""
        from wiki.agents.memory import Memory

        return Memory()

    async def run_tool_loop(
        self,
        system_prompt: str,
        user_prompt: str,
        memory: Any,
        *,
        nudge_message: str = "Please use the available tools to gather information.",
        max_history_messages: int = 30,
        event_callback: EventCallback = None,
    ) -> Any:
        """Multi-round ReAct loop: LLM picks tools → execute → incorporate → repeat.

        Uses self._tool_registry for tool schemas and dispatch.
        Uses self.incorporate() to store results in memory.
        """
        if not self._tool_registry.has_tools():
            return memory

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        total_tool_calls = 0
        has_nonempty_result = False

        for round_num in range(self._max_rounds):
            if event_callback:
                await event_callback(
                    ThinkingEvent(
                        round_num=round_num + 1,
                        text=(
                            "Analyzing and planning "
                            f"(round {round_num + 1})..."
                        ),
                    )
                )
            round_tools = self._tool_registry.get_tools_for_round(
                round_num + 1, has_empty=not has_nonempty_result and total_tool_calls > 0,
            )
            if not round_tools:
                break

            try:
                response = await self._llm.complete_with_tools(messages, round_tools)
            except Exception:
                log.warning("run_tool_loop_llm_failed", round=round_num, exc_info=True)
                break

            tool_calls = response.get("tool_calls")

            if not tool_calls:
                if round_num < 2 and total_tool_calls == 0 and nudge_message:
                    messages.append(response)
                    messages.append({"role": "user", "content": nudge_message})
                    continue
                break

            messages.append(response)

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    log.warning(
                        "tool_arguments_json_invalid",
                        tool=tool_name,
                        arguments_preview=str(func.get("arguments", ""))[:200],
                    )
                    args = {}

                if event_callback:
                    await event_callback(ToolCallEvent(tool=tool_name, args=args))

                result = await self._tool_registry.dispatch(tool_name, args)

                if event_callback:
                    summary = self._summarize_tool_result(result)
                    await event_callback(ToolResultEvent(tool=tool_name, summary=summary))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:6000],
                })
                self.incorporate(tool_name, result, memory)

                if result and "error" not in result:
                    has_nonempty_result = True

            total_tool_calls += len(tool_calls)
            if total_tool_calls >= self._max_tool_calls:
                break

            if len(messages) > max_history_messages:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

        return memory

    async def run_generation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Single-pass text generation without tools."""
        try:
            return await self._llm.generate(prompt=user_prompt, system=system_prompt)
        except Exception:
            log.warning("run_generation_failed", exc_info=True)
            return ""
