"""Guard rails for Wiki generation harness."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardRailViolation:
    rule: str
    message: str
    action: str  # "warn", "block", "truncate"


class HarnessGuardRails:
    MAX_DUPLICATE_QUERIES = 2
    MIN_OUTPUT_LENGTH = 500
    MAX_OUTPUT_LENGTH = 15000

    def __init__(self) -> None:
        self._query_history: list[str] = []

    def check_tool_call(self, tool_name: str, params: dict) -> GuardRailViolation | None:
        key = f"{tool_name}:{sorted(params.items())}"
        count = self._query_history.count(key)
        if count >= self.MAX_DUPLICATE_QUERIES:
            return GuardRailViolation(
                rule="duplicate_query",
                message=f"Query '{tool_name}' called {count + 1} times with same params",
                action="block",
            )
        self._query_history.append(key)
        return None

    def check_output(self, content: str) -> list[GuardRailViolation]:
        violations: list[GuardRailViolation] = []
        if len(content) < self.MIN_OUTPUT_LENGTH:
            violations.append(GuardRailViolation(
                rule="too_short",
                message=f"Output {len(content)} chars < {self.MIN_OUTPUT_LENGTH}",
                action="warn",
            ))
        if len(content) > self.MAX_OUTPUT_LENGTH:
            violations.append(GuardRailViolation(
                rule="too_long",
                message=f"Output {len(content)} chars > {self.MAX_OUTPUT_LENGTH}",
                action="truncate",
            ))
        return violations
