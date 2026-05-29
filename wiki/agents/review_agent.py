from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from core.log import get_logger

log = get_logger(__name__)


@dataclass
class QualityIssue:
    category: str  # "hallucination"|"citation"|"structure"|"naming"|"truncation"
    severity: Literal["info", "warning", "error"]
    description: str
    location: str | None = None


@dataclass
class QualityVerdict:
    status: Literal["pass", "warn", "fail"]
    confidence: float  # 0-1
    issues: list[QualityIssue] = field(default_factory=list)
    heal_instructions: str | None = None


_PART_N_PATTERN = re.compile(r"(?i)^#+\s*(part\s*\d+|第\s*\d+\s*部分)", re.MULTILINE)


class ReviewAgent:
    """Framework-level quality review agent. Deterministic checks only."""

    async def review(self, content: str, metadata: dict) -> QualityVerdict:
        checks = [
            self._check_structure(content, metadata),
            self._check_topic_naming(content),
            self._check_code_blocks(content),
        ]
        all_issues = []
        for result in checks:
            all_issues.extend(result)
        return self._aggregate(all_issues)

    def _check_structure(self, content: str, metadata: dict) -> list[QualityIssue]:
        issues = []
        lines = content.split("\n")
        sections = []
        current_heading = None
        current_content = []

        for line in lines:
            if line.startswith("#"):
                if current_heading is not None:
                    sections.append((current_heading, "\n".join(current_content).strip()))
                current_heading = line
                current_content = []
            else:
                current_content.append(line)
        if current_heading is not None:
            sections.append((current_heading, "\n".join(current_content).strip()))

        # Check for empty sections
        for heading, body in sections:
            if not body.strip():
                issues.append(
                    QualityIssue(
                        category="structure",
                        severity="warning",
                        description=f"Empty section: {heading.strip()}",
                        location=heading.strip(),
                    )
                )

        expected = metadata.get("expected_sections", 0)
        if expected and len(sections) < expected:
            issues.append(
                QualityIssue(
                    category="structure",
                    severity="warning",
                    description=f"Expected {expected} sections, found {len(sections)}",
                )
            )

        return issues

    def _check_topic_naming(self, content: str) -> list[QualityIssue]:
        issues = []
        for match in _PART_N_PATTERN.finditer(content):
            issues.append(
                QualityIssue(
                    category="naming",
                    severity="error",
                    description=f"Mechanical Part N naming: '{match.group().strip()}'",
                    location=match.group().strip(),
                )
            )
        return issues

    def _check_code_blocks(self, content: str) -> list[QualityIssue]:
        issues = []
        fence_count = content.count("```")
        if fence_count % 2 != 0:
            issues.append(
                QualityIssue(
                    category="truncation",
                    severity="error",
                    description="Unclosed code fence (odd number of ``` markers)",
                )
            )
        return issues

    def _aggregate(self, issues: list[QualityIssue]) -> QualityVerdict:
        has_error = any(i.severity == "error" for i in issues)
        has_warning = any(i.severity == "warning" for i in issues)

        if has_error:
            heal_parts = [f"- [{i.category}] {i.description}" for i in issues if i.severity == "error"]
            return QualityVerdict(
                status="fail",
                confidence=1.0 - 0.1 * len(issues),
                issues=issues,
                heal_instructions="Fix these issues:\n" + "\n".join(heal_parts),
            )
        if has_warning:
            return QualityVerdict(status="warn", confidence=1.0 - 0.05 * len(issues), issues=issues)
        return QualityVerdict(status="pass", confidence=1.0, issues=issues)
