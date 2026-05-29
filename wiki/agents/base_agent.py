from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger
from wiki.agents.events import EventCallback
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
    enable_compaction: bool = False
    compaction_model: str | None = None
    compaction_interval: int = 10
    compaction_keep_recent: int = 3
    compaction_trigger_ratio: float = 0.75
    micro_compact_tool_threshold: int = 20_000
    micro_compact_keep_recent_tools: int = 3
    enable_post_call_guardrail: bool = False
    result_truncate_chars: int = 6000
    event_callback: EventCallback = None
    ctx: Any = None  # RunContext instance, passed to tool dispatch
    input_guardrails: _InputGuardrailList = field(default_factory=list)
    output_guardrails: _OutputGuardrailList = field(default_factory=list)
    tracer: Any = None  # AgentTracer instance for span tracking


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
                sig = inspect.signature(tool.handler)
                accepts_ctx = "ctx" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                if accepts_ctx:
                    result = await tool.handler(validated_args, ctx)
                else:
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


class LLMGenerationError(Exception):
    """Raised when the LLM fails to produce output."""

    pass


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

    async def remember(self, question: str, answer: str, confidence: float = 0.7) -> dict:
        """Store important findings to long-term memory.

        NOTE: Register via @function_tool when ready for production.
        """
        if not getattr(self, "_memory_backend", None):
            return {"error": "memory_backend_not_configured", "stored": False}
        if confidence < 0.5:
            return {"error": "confidence_too_low", "stored": False}
        count = getattr(self, "_remember_call_count", 0)
        if count >= 5:
            return {"error": "remember_rate_limit_exceeded", "limit": 5, "stored": False}
        self._remember_call_count = count + 1
        uid = await self._memory_backend.store(
            question=question.strip(), answer=answer.strip(), confidence=confidence
        )
        return {"stored": True, "uid": uid, "confidence": confidence}

    def restrict_tools(self, allowed: list[str]) -> None:
        """Restrict available tools to the given allowlist (intersects with tier)."""
        self._tool_allowlist = frozenset(allowed)

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
        from wiki.agents.runner import LoopConfig, run_agent_loop

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

        effective_ctx = ctx if ctx is not None else config.ctx

        loop_config = LoopConfig(
            max_rounds=config.max_rounds,
            max_tool_calls=config.max_tool_calls,
            max_history_messages=config.max_history_messages,
            nudge_message=config.nudge_message,
            enable_early_stop=config.enable_early_stop,
            early_stop_max_empty=config.early_stop_max_empty,
            enable_context_trim=config.enable_context_trim,
            context_trim_max_chars=config.context_trim_max_chars,
            context_trim_keep_recent=config.context_trim_keep_recent,
            enable_compaction=config.enable_compaction,
            compaction_model=config.compaction_model,
            compaction_interval=config.compaction_interval,
            compaction_keep_recent=config.compaction_keep_recent,
            compaction_trigger_ratio=config.compaction_trigger_ratio,
            micro_compact_tool_threshold=config.micro_compact_tool_threshold,
            micro_compact_keep_recent_tools=config.micro_compact_keep_recent_tools,
            enable_post_call_guardrail=config.enable_post_call_guardrail,
            result_truncate_chars=config.result_truncate_chars,
            input_guardrails=config.input_guardrails,
            output_guardrails=config.output_guardrails,
            event_callback=config.event_callback,
            tracer=config.tracer,
            ctx=effective_ctx,
            detect_repeated_calls=True,
        )

        result = await run_agent_loop(
            self, system_prompt, user_prompt, memory, config=loop_config
        )
        return result.memory

    async def run_generation(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        config: RunConfig | None = None,
        ctx: Any = None,
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
                output = self._render_output(result)
            except Exception:
                log.warning("structured_output_failed_fallback_to_text", exc_info=True)
                output = None
            if output is not None:
                await self._run_output_guardrails(output, config, ctx)
                return output
        try:
            text = await self._llm.generate(prompt=user_prompt, system=system_prompt)
        except Exception as exc:
            log.warning("run_generation_failed", exc_info=True)
            raise LLMGenerationError(f"LLM generation failed: {exc}") from exc
        if text:
            await self._run_output_guardrails(text, config, ctx)
        return text

    async def _run_output_guardrails(
        self, output: str, config: RunConfig | None, ctx: Any
    ) -> None:
        """Run output guardrails if configured. Raises GuardrailTrippedError on tripwire."""
        if not config or not config.output_guardrails:
            return
        effective_ctx = ctx if ctx is not None else config.ctx
        from wiki.agents.guardrails import GuardrailTrippedError

        for guard in config.output_guardrails:
            result = await guard.check(output, effective_ctx)
            if result.tripwire:
                raise GuardrailTrippedError(
                    result.output_info, guardrail_name=type(guard).__name__
                )
            if not result.passed:
                log.warning(
                    "output_guardrail_soft_fail",
                    guardrail=type(guard).__name__,
                    info=result.output_info,
                )
