"""Tool guardrail protocol and default implementation.

Pre/post hooks around tool dispatch to validate args and sanitize results.
"""
from __future__ import annotations

from typing import Protocol


class ToolGuardrail(Protocol):
    """Protocol for tool call validation hooks."""

    async def pre_call(self, tool_name: str, args: dict) -> dict | None:
        """Validate/transform args before tool execution.

        Return None to reject the call (will produce an error result).
        Return (possibly modified) args to proceed.
        """
        ...

    async def post_call(self, tool_name: str, args: dict, result: str) -> str:
        """Validate/transform tool result before it enters memory.

        Return the (possibly modified) result string.
        """
        ...


class DefaultToolGuardrail:
    """Built-in guardrails for common quality issues."""

    MAX_RESULT_CHARS = 8000

    _REQUIRED_PARAMS: dict[str, list[str]] = {
        "query_call_chain": ["method_name"],
        "grep_code": ["pattern"],
        "read_code": ["entity_name"],
        "query_callers": ["entity_name"],
        "query_callees": ["entity_name"],
    }

    async def pre_call(self, tool_name: str, args: dict) -> dict | None:
        required = self._REQUIRED_PARAMS.get(tool_name)
        if required:
            for param in required:
                val = args.get(param)
                if not val or (isinstance(val, str) and not val.strip()):
                    return None
        return args

    async def post_call(self, tool_name: str, args: dict, result: str) -> str:
        if not result or not result.strip():
            return f"[EMPTY_RESULT] No data returned for {tool_name}({args})"
        if len(result) > self.MAX_RESULT_CHARS:
            return result[: self.MAX_RESULT_CHARS] + "\n[TRUNCATED]"
        return result
