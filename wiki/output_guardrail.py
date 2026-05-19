"""Output guardrail chain for wiki page quality validation.

Provides a unified quality gate that replaces scattered checks with
a composable chain of independent check functions.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class CheckResult:
    name: str
    passed: bool
    score: float
    issues: list[str] = field(default_factory=list)


@dataclass
class GuardrailResult:
    passed: bool
    details: dict[str, CheckResult] = field(default_factory=dict)

    @property
    def total_score(self) -> float:
        if not self.details:
            return 0.0
        return sum(r.score for r in self.details.values()) / len(self.details)


class OutputCheck(Protocol):
    name: str

    async def check(self, page_content: str, context: dict) -> CheckResult: ...


class FormatCheck:
    """Validate Markdown structure: headings present, no thinking leaks."""

    name = "format"

    _THINKING_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
    _H1_RE = re.compile(r"^# .+", re.MULTILINE)
    _H2_RE = re.compile(r"^## .+", re.MULTILINE)

    async def check(self, page_content: str, context: dict) -> CheckResult:
        issues: list[str] = []
        score = 1.0

        if not self._H1_RE.search(page_content) and not self._H2_RE.search(page_content):
            issues.append("No heading structure found")
            score -= 0.5

        if self._THINKING_RE.search(page_content):
            issues.append("Thinking leak detected (<think> tags)")
            score -= 0.5

        return CheckResult(
            name=self.name,
            passed=not issues,
            score=max(0.0, score),
            issues=issues,
        )


class CoverageCheck:
    """Compare mentioned modules against expected modules."""

    name = "coverage"

    async def check(self, page_content: str, context: dict) -> CheckResult:
        module_names: list[str] = context.get("module_names", [])
        if not module_names:
            return CheckResult(name=self.name, passed=True, score=1.0)

        content_lower = page_content.lower()
        covered = sum(1 for m in module_names if m.lower() in content_lower)
        score = covered / len(module_names)

        issues = []
        if score < 0.8:
            uncovered = [m for m in module_names if m.lower() not in content_lower]
            issues.append(f"Uncovered modules: {', '.join(uncovered[:5])}")

        return CheckResult(
            name=self.name,
            passed=score >= 0.8,
            score=round(score, 4),
            issues=issues,
        )


class LengthCheck:
    """Ensure page length is within acceptable bounds."""

    name = "length"
    MIN_CHARS = 200
    MAX_CHARS = 80000

    async def check(self, page_content: str, context: dict) -> CheckResult:
        length = len(page_content)
        issues: list[str] = []

        if length < self.MIN_CHARS:
            issues.append(f"Too short: {length} chars (min {self.MIN_CHARS})")
            return CheckResult(name=self.name, passed=False, score=0.2, issues=issues)
        if length > self.MAX_CHARS:
            issues.append(f"Too long: {length} chars (max {self.MAX_CHARS})")
            return CheckResult(name=self.name, passed=False, score=0.5, issues=issues)

        return CheckResult(name=self.name, passed=True, score=1.0)


class OutputGuardrailChain:
    """Compose multiple OutputChecks and evaluate them concurrently."""

    def __init__(self, checks: list[OutputCheck]) -> None:
        self._checks = checks

    async def evaluate(self, page_content: str, context: dict) -> GuardrailResult:
        results = await asyncio.gather(
            *(c.check(page_content, context) for c in self._checks)
        )
        details = {r.name: r for r in results}
        return GuardrailResult(
            passed=all(r.passed for r in results),
            details=details,
        )
