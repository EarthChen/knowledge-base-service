from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger
from wiki.agents.context_compactor import ExploreCompactor, micro_compact, snip_compact
from wiki.agents.events import EventCallback, ThinkingEvent, ToolCallEvent, ToolResultEvent
from wiki.agents.token_budget import TokenBudgetManager

log = get_logger(__name__)

_InputGuardrailList = list[Any]
_OutputGuardrailList = list[Any]


@dataclass
class LoopHooks:
    """Optional callbacks for loop customization.

    on_no_tool_calls(round_num, text_output, total_tool_calls) -> str | None
        Called when LLM returns text without tool calls.
        Return a string to inject as user message (nudge) and continue the loop.
        Return None to accept the text output and exit the loop.

    on_loop_complete(memory) -> str | None
        Called after the loop exits (by any exit condition).
        Return a string to use as final_output (fallback generation).
        Return None to keep whatever final_output the loop produced.
    """

    on_no_tool_calls: Callable[[int, str | None, int], Awaitable[str | None]] | None = None
    on_loop_complete: Callable[[Any], Awaitable[str | None]] | None = None


@dataclass
class LoopConfig:
    """Configuration for run_agent_loop execution."""

    max_rounds: int = 6
    max_tool_calls: int = 30
    max_history_messages: int = 30
    nudge_message: str = "Please use the available tools to gather information."

    # Timeouts (seconds); None = no timeout
    llm_call_timeout: float | None = 120.0
    tool_call_timeout: float | None = 60.0

    # Early stop
    enable_early_stop: bool = False
    early_stop_max_empty: int = 2

    # Context trim
    enable_context_trim: bool = False
    context_trim_max_chars: int = 60000
    context_trim_keep_recent: int = 3

    # Context compression
    enable_compaction: bool = False
    compaction_model: str | None = None
    compaction_interval: int = 10
    compaction_keep_recent: int = 3
    compaction_trigger_ratio: float = 0.75
    micro_compact_tool_threshold: int = 20_000
    micro_compact_keep_recent_tools: int = 3

    # Repeated call detection
    detect_repeated_calls: bool = True
    max_consecutive_repeats: int = 2
    detect_alternating_repeats: bool = True  # requires detect_repeated_calls=True
    alternating_window_size: int = 6
    alternating_unique_threshold: float = 0.5  # unique_ratio < threshold triggers block

    # Guardrails
    enable_post_call_guardrail: bool = False
    result_truncate_chars: int = 6000
    input_guardrails: _InputGuardrailList = field(default_factory=list)
    output_guardrails: _OutputGuardrailList = field(default_factory=list)

    # Hooks
    hooks: LoopHooks = field(default_factory=LoopHooks)

    # Observability
    event_callback: EventCallback = None
    tracer: Any = None
    ctx: Any = None

    # LangGraph heartbeat — resets idle_timeout timer
    heartbeat: Callable[[], None] | None = None


@dataclass
class AgentLoopResult:
    """Structured result from run_agent_loop."""

    memory: Any
    final_output: str | None = None
    total_rounds: int = 0
    total_tool_calls: int = 0
    repeated_calls_detected: int = 0
    exit_reason: str = "max_rounds"


async def _apply_context_compression(
    messages: list[dict],
    *,
    budget_mgr: TokenBudgetManager,
    compactor: ExploreCompactor | None,
    memory: Any,
    config: LoopConfig,
    _last_compact_round: list[int],
    round_num: int,
) -> list[dict]:
    """Apply progressive context compression (L0-L4)."""
    snap = budget_mgr.snapshot(messages)
    level = snap.recommended_level
    if snap.usage_ratio >= config.compaction_trigger_ratio and level < 3:
        level = 3
    snip_threshold = config.result_truncate_chars if config.result_truncate_chars > 0 else 2000

    # L1 needs sufficient clearable content
    if level == 1 and snap.clearable_tool_chars < config.micro_compact_tool_threshold:
        level = 0

    if level == 0:
        return messages
    if level == 1:
        return micro_compact(messages, keep_recent_n=config.micro_compact_keep_recent_tools)
    if level == 2:
        return snip_compact(messages, max_tool_chars=snip_threshold)
    if level == 3 and not compactor:
        return snip_compact(messages, max_tool_chars=snip_threshold)
    if level == 3 and compactor:
        # Rate limit: at most 1 compact per interval
        if _last_compact_round and (round_num - _last_compact_round[0]) < config.compaction_interval:
            return snip_compact(messages, max_tool_chars=snip_threshold)
        try:
            from wiki.context_manager import ContextManager

            boundary = ContextManager._find_recent_boundary(
                ContextManager(keep_recent_rounds=config.compaction_keep_recent),
                messages,
            )
            result = await compactor.compact(messages, 1, boundary)
            if memory and hasattr(memory, "inject_findings"):
                memory.inject_findings(result.key_findings)
            _last_compact_round.clear()
            _last_compact_round.append(round_num)
            return [messages[0], {"role": "user", "content": f"[探索摘要]\n{result.summary}"}] + messages[boundary:]
        except Exception as e:
            log.warning("compaction_l3_failed", error=str(e))
            return snip_compact(messages, max_tool_chars=snip_threshold)
    if level >= 4:
        if memory and hasattr(memory, "to_prompt"):
            mem_prompt = (
                memory.to_prompt(max_chars=40_000)
                if callable(getattr(memory, "to_prompt", None))
                else str(memory)[:40_000]
            )
            return [messages[0], {"role": "user", "content": f"[WorkingMemory 兜底]\n{mem_prompt}"}]
        log.warning("compaction_l4_no_memory_fallback")
        return snip_compact(messages, max_tool_chars=500)

    return messages


async def run_agent_loop(
    agent: Any,
    system_prompt: str,
    user_prompt: str,
    memory: Any,
    *,
    config: LoopConfig | None = None,
) -> AgentLoopResult:
    """Execute an agent's tool loop with configurable behavior.

    This is the single execution engine for all agent loops.
    GenericAgent.run_tool_loop() delegates to this function.
    """
    if config is None:
        config = LoopConfig()

    effective_ctx = config.ctx
    result = AgentLoopResult(memory=memory)

    # --- Input guardrails ---
    if config.input_guardrails:
        from wiki.agents.guardrails import GuardrailTrippedError

        for guard in config.input_guardrails:
            gr = await guard.check(user_prompt, effective_ctx)
            if gr.tripwire:
                raise GuardrailTrippedError(gr.output_info, guardrail_name=type(guard).__name__)
            if not gr.passed:
                log.warning("input_guardrail_soft_fail", guardrail=type(guard).__name__, info=gr.output_info)

    if not agent._tool_registry.has_tools():
        result.exit_reason = "no_tools"
    else:
        from wiki.context_manager import ContextManager
        from wiki.early_stop import EarlyStopDetector

        tracer = config.tracer
        root_span = None
        if tracer:
            root_span = tracer.start_span("run_agent_loop", kind="agent_run")

        early_stop = (
            EarlyStopDetector(max_empty_rounds=config.early_stop_max_empty)
            if config.enable_early_stop
            else None
        )
        ctx_mgr = (
            ContextManager(
                max_context_chars=config.context_trim_max_chars,
                keep_recent_rounds=config.context_trim_keep_recent,
            )
            if config.enable_context_trim
            else None
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        has_nonempty_result = False
        _recent_signatures: list[str] = []
        budget_mgr = (
            TokenBudgetManager(compaction_trigger_ratio=config.compaction_trigger_ratio)
            if config.enable_compaction
            else None
        )
        compactor = (
            ExploreCompactor(llm_port=agent._llm, model=config.compaction_model)
            if config.enable_compaction
            else None
        )
        _last_compact_round: list[int] = []

        for round_num in range(config.max_rounds):
            result.total_rounds = round_num + 1

            if config.event_callback:
                await config.event_callback(
                    ThinkingEvent(round_num=round_num + 1, text=f"Analyzing (round {round_num + 1})...")
                )

            round_tools = agent._tool_registry.get_tools_for_round(
                round_num + 1,
                has_empty=not has_nonempty_result and result.total_tool_calls > 0,
            )
            if allowlist := getattr(agent, "_tool_allowlist", None):
                if isinstance(allowlist, (frozenset, set, list, tuple)):
                    round_tools = [t for t in round_tools if t.get("function", {}).get("name") in allowlist]
            if not round_tools:
                result.exit_reason = "no_tools"
                break

            try:
                if config.heartbeat:
                    config.heartbeat()
                coro = agent._llm.complete_with_tools(messages, round_tools)
                if config.llm_call_timeout:
                    response = await asyncio.wait_for(coro, timeout=config.llm_call_timeout)
                else:
                    response = await coro
                if config.heartbeat:
                    config.heartbeat()
            except TimeoutError:
                log.warning("run_agent_loop_llm_timeout", round=round_num, timeout=config.llm_call_timeout)
                result.exit_reason = "llm_timeout"
                break
            except Exception:
                # LLM failures break the loop immediately; partial tool results remain in
                # ``memory`` and ``result``. ``on_loop_complete`` still runs after the loop
                # (see below) so callers can recover or synthesize fallback output.
                log.warning("run_agent_loop_llm_failed", round=round_num, exc_info=True)
                result.exit_reason = "llm_error"
                break

            tool_calls = response.get("tool_calls")

            if not tool_calls:
                text_content = response.get("content") or None
                if config.hooks.on_no_tool_calls:
                    nudge = await config.hooks.on_no_tool_calls(
                        round_num, text_content, result.total_tool_calls
                    )
                    if nudge is not None:
                        messages.append(response)
                        messages.append({"role": "user", "content": nudge})
                        continue
                    result.final_output = text_content
                    result.exit_reason = "text_output"
                    break
                result.final_output = text_content
                if round_num < 2 and result.total_tool_calls == 0 and config.nudge_message:
                    messages.append(response)
                    messages.append({"role": "user", "content": config.nudge_message})
                    continue
                result.exit_reason = "text_output"
                break

            messages.append(response)
            round_result_strs: list[str] = []

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    log.warning("tool_arguments_json_invalid", tool=tool_name)
                    args = {}

                if config.detect_repeated_calls:
                    sig = (
                        f"{tool_name}:"
                        f"{hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()[:8]}"
                    )
                    _recent_signatures.append(sig)
                    if len(_recent_signatures) >= config.max_consecutive_repeats:
                        tail = _recent_signatures[-config.max_consecutive_repeats :]
                        if len(set(tail)) == 1 and len(tail) == config.max_consecutive_repeats:
                            result.repeated_calls_detected += 1
                            log.info(
                                "repeated_tool_call_detected",
                                tool=tool_name,
                                count=config.max_consecutive_repeats,
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": json.dumps(
                                    {
                                        "error": (
                                            f"Repeated call detected. You called {tool_name} "
                                            f"with identical arguments {config.max_consecutive_repeats} "
                                            "times. Try a different approach."
                                        )
                                    },
                                    ensure_ascii=False,
                                ),
                            })
                            continue

                    if (
                        config.detect_alternating_repeats
                        and len(_recent_signatures) >= config.alternating_window_size
                    ):
                        window = _recent_signatures[-config.alternating_window_size :]
                        unique_ratio = len(set(window)) / len(window)
                        if unique_ratio < config.alternating_unique_threshold:
                            result.repeated_calls_detected += 1
                            log.info(
                                "alternating_repeat_detected",
                                tool=tool_name,
                                window_size=config.alternating_window_size,
                                unique_ratio=round(unique_ratio, 2),
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": json.dumps(
                                    {
                                        "error": (
                                            f"Alternating repeat pattern detected in last "
                                            f"{config.alternating_window_size} calls "
                                            f"(only {len(set(window))} unique patterns). "
                                            "Try a completely different approach or tool."
                                        )
                                    },
                                    ensure_ascii=False,
                                ),
                            })
                            continue

                if config.event_callback:
                    await config.event_callback(ToolCallEvent(tool=tool_name, args=args))

                tool_span = None
                if tracer:
                    tool_span = tracer.start_span(tool_name, kind="tool_call")

                try:
                    if config.heartbeat:
                        config.heartbeat()
                    dispatch_coro = agent._tool_registry.dispatch(
                        tool_name, args, post_call=config.enable_post_call_guardrail, ctx=effective_ctx
                    )
                    if config.tool_call_timeout:
                        tool_result, result_str = await asyncio.wait_for(
                            dispatch_coro, timeout=config.tool_call_timeout
                        )
                    else:
                        tool_result, result_str = await dispatch_coro
                    if config.heartbeat:
                        config.heartbeat()
                except TimeoutError:
                    log.warning("tool_call_timeout", tool=tool_name, timeout=config.tool_call_timeout)
                    tool_result = {"error": f"Tool {tool_name} timed out after {config.tool_call_timeout}s"}
                    result_str = json.dumps(tool_result, ensure_ascii=False)
                except Exception as exc:
                    log.exception("tool_call_error", tool=tool_name)
                    tool_result = {"error": f"Tool {tool_name} failed: {exc}"}
                    result_str = json.dumps(tool_result, ensure_ascii=False)

                if tool_span and tracer:
                    status = "error" if "error" in tool_result else "completed"
                    tracer.end_span(tool_span, status=status)

                if config.event_callback:
                    summary = json.dumps(tool_result, ensure_ascii=False, default=str)[:200]
                    await config.event_callback(ToolResultEvent(tool=tool_name, summary=summary))

                if config.result_truncate_chars and len(result_str) > config.result_truncate_chars:
                    result_str = result_str[: config.result_truncate_chars]

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result_str,
                })
                round_result_strs.append(result_str)
                agent.incorporate(tool_name, tool_result, memory)

                if tool_result and "error" not in tool_result:
                    has_nonempty_result = True

            result.total_tool_calls += len(tool_calls)
            if result.total_tool_calls >= config.max_tool_calls:
                result.exit_reason = "max_tool_calls"
                break

            if early_stop and early_stop.should_stop(round_result_strs):
                log.info("run_agent_loop_early_stop", round=round_num)
                result.exit_reason = "early_stop"
                break

            if config.enable_compaction and budget_mgr is not None:
                messages = await _apply_context_compression(
                    messages,
                    budget_mgr=budget_mgr,
                    compactor=compactor,
                    memory=memory,
                    config=config,
                    _last_compact_round=_last_compact_round,
                    round_num=round_num,
                )
            elif ctx_mgr:
                messages = ctx_mgr.trim(messages)
            elif len(messages) > config.max_history_messages:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

        if root_span and tracer:
            tracer.end_span(root_span)

    # --- on_loop_complete hook ---
    if config.hooks.on_loop_complete:
        fallback_output = await config.hooks.on_loop_complete(memory)
        if fallback_output is not None:
            result.final_output = fallback_output
            result.exit_reason = "hook_fallback"

    # --- Output guardrails ---
    if config.output_guardrails and result.final_output:
        from wiki.agents.guardrails import GuardrailTrippedError

        for guard in config.output_guardrails:
            gr = await guard.check(result.final_output, effective_ctx)
            if gr.tripwire:
                raise GuardrailTrippedError(gr.output_info, guardrail_name=type(guard).__name__)
            if not gr.passed:
                log.warning(
                    "output_guardrail_soft_fail",
                    guardrail=type(guard).__name__,
                    info=gr.output_info,
                )

    return result
