"""Unified guardrails for agent tool loops.

Provides input, output, and tool guardrail protocols with tripwire
semantics for immediate loop abort.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from wiki.agents.context import RunContext


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""

    passed: bool
    output_info: str = ""
    tripwire: bool = False


class GuardrailTrippedError(Exception):
    """Raised when a guardrail with tripwire=True fires."""

    def __init__(self, message: str, *, guardrail_name: str = ""):
        super().__init__(message)
        self.guardrail_name = guardrail_name


class InputGuardrail(Protocol):
    """Runs before the first LLM call in run_tool_loop."""

    async def check(self, user_prompt: str, ctx: RunContext) -> GuardrailResult: ...


class OutputGuardrail(Protocol):
    """Runs after the final output is produced."""

    async def check(self, output: str, ctx: RunContext) -> GuardrailResult: ...


class ToolGuardrailWithCtx(Protocol):
    """Runs around each tool dispatch with RunContext access."""

    async def pre_call(self, name: str, args: dict, ctx: RunContext) -> dict | None: ...

    async def post_call(self, name: str, args: dict, result: str, ctx: RunContext) -> str: ...


class PromptLengthGuardrail:
    """Input guardrail that blocks prompts exceeding a character limit."""

    def __init__(self, max_chars: int = 100_000) -> None:
        self._max_chars = max_chars

    async def check(self, user_prompt: str, ctx: RunContext) -> GuardrailResult:
        if len(user_prompt) > self._max_chars:
            return GuardrailResult(
                passed=False,
                tripwire=True,
                output_info=f"prompt length {len(user_prompt)} exceeds max {self._max_chars}",
            )
        return GuardrailResult(passed=True)
