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
    should_heal: bool = False


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


class LanguageConsistencyCheck:
    """Check that content language matches target language setting."""

    name = "language_consistency"

    _CN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
    _CHINESE_TARGETS = frozenset({"简体中文", "繁體中文", "zh-CN", "zh-TW", "zh"})
    _CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)
    _BACKTICK_RE = re.compile(r"`[^`]+`")

    def _compute_cn_ratio(self, text: str) -> float:
        cleaned = self._CODE_BLOCK_RE.sub("", text)
        cleaned = self._BACKTICK_RE.sub("", cleaned)
        total_chars = len(cleaned.strip())
        if total_chars == 0:
            return 0.0
        cn_chars = len(self._CN_CHAR_RE.findall(cleaned))
        return cn_chars / total_chars

    async def check(self, page_content: str, context: dict) -> CheckResult:
        target = context.get("target_language", "")
        if target not in self._CHINESE_TARGETS:
            return CheckResult(name=self.name, passed=True, score=1.0)

        threshold = context.get("cn_ratio_threshold", 0.4)
        cn_ratio = self._compute_cn_ratio(page_content)

        if cn_ratio < threshold:
            page_type = context.get("page_type", "")
            result = CheckResult(
                name=self.name,
                passed=False,
                score=cn_ratio,
                issues=[f"CN ratio {cn_ratio:.2f} below threshold {threshold} for target '{target}'"],
            )
            if page_type == "topic":
                result.should_heal = True
            return result
        return CheckResult(name=self.name, passed=True, score=min(1.0, cn_ratio * 2))


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


@dataclass
class TermCheckResult:
    has_violations: bool = False
    violations: list[str] = field(default_factory=list)


class TermConsistencyCheck:
    """Soft guardrail: check if English terms appear without their Chinese equivalents."""

    async def evaluate(self, content: str, context: dict) -> TermCheckResult:
        glossary = context.get("term_glossary", {})
        if not glossary:
            return TermCheckResult()

        violations: list[str] = []
        content_lower = content.lower()
        for eng_term, chn_term in glossary.items():
            if eng_term.lower() in content_lower and chn_term not in content:
                violations.append(f"'{eng_term}' found without '{chn_term}'")

        return TermCheckResult(
            has_violations=len(violations) > 0,
            violations=violations,
        )


class SensitiveContentCheck:
    """Detect sensitive information patterns in wiki content."""

    name = "sensitive_content"

    _PATTERNS = [
        re.compile(r"https?://(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|internal\.|localhost)\S*", re.IGNORECASE),
        re.compile(r"((?:password|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*)\S+", re.IGNORECASE),
    ]

    async def check(self, page_content: str, context: dict) -> CheckResult:
        findings: list[str] = []
        for pattern in self._PATTERNS:
            matches = pattern.findall(page_content)
            if matches:
                findings.extend(str(m) for m in matches[:3])
        if findings:
            return CheckResult(
                name=self.name,
                passed=False,
                score=0.0,
                issues=[f"Sensitive patterns detected: {len(findings)} matches"],
            )
        return CheckResult(name=self.name, passed=True, score=1.0)
