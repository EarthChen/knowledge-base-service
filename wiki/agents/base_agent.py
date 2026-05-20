from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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

# Type aliases for guardrail lists (avoid circular import)
_InputGuardrailList = list[Any]
_OutputGuardrailList = list[Any]


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


@dataclass
class RunConfig:
    """Configuration for the unified agent tool loop."""

    max_rounds: int = 6
    max_tool_calls: int = 30
    max_history_messages: int = 30
    nudge_message: str = "Please use the available tools to gather information."
    enable_early_stop: bool = False
    early_stop_max_empty: int = 2
    enable_context_trim: bool = False
    context_trim_max_chars: int = 60000
    context_trim_keep_recent: int = 3
    enable_post_call_guardrail: bool = False
    result_truncate_chars: int = 6000
    event_callback: EventCallback = None
    ctx: Any = None  # RunContext instance, passed to tool dispatch
    input_guardrails: _InputGuardrailList = field(default_factory=list)
    output_guardrails: _OutputGuardrailList = field(default_factory=list)


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

    async def dispatch(
        self, name: str, args: dict[str, Any], *, post_call: bool = False, ctx: Any = None
    ) -> tuple[dict[str, Any], str]:
        """Dispatch a tool call. Returns (result_data, result_str)."""
        tool = self._tools.get(name)
        if tool is None:
            err = {"error": f"Unknown tool: {name}"}
            return err, json.dumps(err, ensure_ascii=False)

        validated_args = await self._guardrail.pre_call(name, args)
        if validated_args is None:
            err = {"error": f"rejected by guardrail: {name} missing required params"}
            return err, json.dumps(err, ensure_ascii=False)

        try:
            if ctx is not None:
                try:
                    result = await tool.handler(validated_args, ctx)
                except TypeError:
                    result = await tool.handler(validated_args)
            else:
                result = await tool.handler(validated_args)
        except Exception as exc:
            log.warning("tool_dispatch_error", tool=name, exc_info=True)
            err = {"error": str(exc)}
            return err, json.dumps(err, ensure_ascii=False)

        result_str = json.dumps(result, ensure_ascii=False, default=str)
        if post_call:
            result_str = await self._guardrail.post_call(name, validated_args, result_str)
        return result, result_str


class GenericAgent(ABC):
    """Pure LLM execution engine — no domain knowledge.

    Subclasses must implement incorporate() and memory_to_prompt()
    to define how tool results map to memory and how memory is
    presented to the LLM.
    """

    output_type: type | None = None

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

    def _render_output(self, structured: dict) -> str:
        return json.dumps(structured, ensure_ascii=False)

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
        config: RunConfig | None = None,
        ctx: Any = None,
        nudge_message: str | None = None,
        max_history_messages: int | None = None,
        event_callback: EventCallback = None,
    ) -> Any:
        """Unified multi-round ReAct loop with optional early stop, context trim, and post-call guardrails.

        Uses self._tool_registry for tool schemas and dispatch.
        Uses self.incorporate() to store results in memory.
        """
        if config is None:
            config = RunConfig(
                max_rounds=self._max_rounds,
                max_tool_calls=self._max_tool_calls,
                nudge_message=nudge_message or "Please use the available tools to gather information.",
                max_history_messages=max_history_messages or 30,
                event_callback=event_callback,
            )
        else:
            if event_callback is not None:
                config.event_callback = event_callback
            if nudge_message is not None:
                config.nudge_message = nudge_message
            if max_history_messages is not None:
                config.max_history_messages = max_history_messages

        effective_ctx = ctx if ctx is not None else (config.ctx if config else None)

        # --- Input guardrails: run before any LLM call ---
        if config.input_guardrails:
            from wiki.agents.guardrails import GuardrailTrippedError

            for guard in config.input_guardrails:
                result = await guard.check(user_prompt, effective_ctx)
                if result.tripwire:
                    raise GuardrailTrippedError(
                        result.output_info,
                        guardrail_name=getattr(guard, "__class__", type(guard)).__name__,
                    )

        if not self._tool_registry.has_tools():
            return memory

        from wiki.early_stop import EarlyStopDetector
        from wiki.context_manager import ContextManager

        early_stop = EarlyStopDetector(max_empty_rounds=config.early_stop_max_empty) if config.enable_early_stop else None
        ctx_mgr = ContextManager(
            max_context_chars=config.context_trim_max_chars,
            keep_recent_rounds=config.context_trim_keep_recent,
        ) if config.enable_context_trim else None

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        total_tool_calls = 0
        has_nonempty_result = False
        final_output: str | None = None

        for round_num in range(config.max_rounds):
            if config.event_callback:
                await config.event_callback(
                    ThinkingEvent(
                        round_num=round_num + 1,
                        text=f"Analyzing and planning (round {round_num + 1})...",
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
                final_output = response.get("content") or None
                if round_num < 2 and total_tool_calls == 0 and config.nudge_message:
                    messages.append(response)
                    messages.append({"role": "user", "content": config.nudge_message})
                    continue
                break

            messages.append(response)
            round_result_strs: list[str] = []

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

                if config.event_callback:
                    await config.event_callback(ToolCallEvent(tool=tool_name, args=args))

                result, result_str = await self._tool_registry.dispatch(
                    tool_name, args, post_call=config.enable_post_call_guardrail, ctx=effective_ctx
                )

                if config.event_callback:
                    summary = self._summarize_tool_result(result)
                    await config.event_callback(ToolResultEvent(tool=tool_name, summary=summary))

                if config.result_truncate_chars and len(result_str) > config.result_truncate_chars:
                    result_str = result_str[:config.result_truncate_chars]

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result_str,
                })
                round_result_strs.append(result_str)
                self.incorporate(tool_name, result, memory)

                if result and "error" not in result:
                    has_nonempty_result = True

            total_tool_calls += len(tool_calls)
            if total_tool_calls >= config.max_tool_calls:
                break

            if early_stop and early_stop.should_stop(round_result_strs):
                log.info("run_tool_loop_early_stop", round=round_num)
                break

            if ctx_mgr:
                messages = ctx_mgr.trim(messages)
            elif len(messages) > config.max_history_messages:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

        # --- Output guardrails: run after the loop completes ---
        if config.output_guardrails and final_output:
            from wiki.agents.guardrails import GuardrailTrippedError

            for guard in config.output_guardrails:
                result = await guard.check(final_output, effective_ctx)
                if result.tripwire:
                    raise GuardrailTrippedError(
                        result.output_info,
                        guardrail_name=getattr(guard, "__class__", type(guard)).__name__,
                    )

        return memory

    async def run_generation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Single-pass text generation without tools. Uses output_type if set."""
        if self.output_type is not None:
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                result = await self._llm.complete_json(
                    messages, schema=self.output_type.model_json_schema()
                )
                return self._render_output(result)
            except Exception:
                log.warning("structured_output_failed_fallback_to_text", exc_info=True)
        try:
            return await self._llm.generate(prompt=user_prompt, system=system_prompt)
        except Exception:
            log.warning("run_generation_failed", exc_info=True)
            return ""
