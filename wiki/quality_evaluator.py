"""Wiki page quality evaluation: structural checks, LLM-as-Judge, aggregation."""

from __future__ import annotations

import json
import re
from typing import Any

from log import get_logger
from wiki.models import (
    ImportanceTier,
    WikiPage,
    WikiPageQualityScore,
)

log = get_logger(__name__)


class WikiQualityEvaluator:
    def __init__(self, llm: Any = None, judge_model: str = "") -> None:
        self._llm = llm
        self._judge_model = judge_model

    def structural_check(self, page: WikiPage) -> WikiPageQualityScore:
        """Quick structural quality assessment without LLM."""
        issues: list[str] = []
        completeness = 0.0
        checks = [
            ("## Overview" in page.content, "missing_overview", 0.25),
            ("## Key components" in page.content or "## Methods" in page.content, "missing_components", 0.25),
            ("## Relationships" in page.content, "missing_relationships", 0.2),
            (len(page.content) > 200, "content_too_short", 0.15),
            (len(page.diagrams) > 0, "no_diagrams", 0.15),
        ]
        for present, issue_id, weight in checks:
            if present:
                completeness += weight
            else:
                issues.append(issue_id)
        return WikiPageQualityScore(
            page_path=page.path,
            completeness=round(completeness, 2),
            helpfulness=round(completeness * 0.8, 2),
            truthfulness=1.0,
            overall=round(completeness * 0.9, 2),
            issues=issues,
        )

    async def llm_judge_evaluate(
        self,
        page: WikiPage,
        source_code: str = "",
        graph_metadata: str = "",
    ) -> WikiPageQualityScore:
        """Full quality evaluation using LLM as judge."""
        if not self._llm:
            return self.structural_check(page)

        prompt = (
            "Evaluate this documentation page on three dimensions.\n\n"
            f"Page content:\n{page.content[:3000]}\n\n"
            f"Source code context:\n{source_code[:2000]}\n\n"
            f"Graph metadata:\n{graph_metadata[:1000]}\n\n"
            "Score each dimension 0.0-1.0 and list any issues:\n"
            "1. Completeness: Does it cover purpose, methods, relationships, usage patterns?\n"
            "2. Helpfulness: Can a developer new to this codebase understand the component?\n"
            "3. Truthfulness: Are code references accurate? Any hallucinations?\n\n"
            'Output JSON: {"completeness": 0.0, "helpfulness": 0.0, "truthfulness": 0.0, "issues": ["issue1"]}'
        )

        try:
            raw = await self._llm.generate(
                prompt,
                system="You are a documentation quality evaluator. Output valid JSON only.",
                model=self._judge_model or None,
            )
            cleaned = raw.strip()
            fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
            if fence_match:
                cleaned = fence_match.group(1).strip()
            result = json.loads(cleaned)
        except (json.JSONDecodeError, Exception):
            log.warning("llm_judge_parse_failed", page=page.path, exc_info=True)
            return self.structural_check(page)

        completeness = max(0.0, min(1.0, float(result.get("completeness", 0))))
        helpfulness = max(0.0, min(1.0, float(result.get("helpfulness", 0))))
        truthfulness = max(0.0, min(1.0, float(result.get("truthfulness", 0))))

        raw_issues = result.get("issues", [])
        if isinstance(raw_issues, list):
            issues = [str(i) for i in raw_issues if i]
        elif isinstance(raw_issues, str):
            issues = [raw_issues] if raw_issues else []
        else:
            issues = []

        return WikiPageQualityScore(
            page_path=page.path,
            completeness=completeness,
            helpfulness=helpfulness,
            truthfulness=truthfulness,
            overall=round((completeness + helpfulness + truthfulness) / 3, 3),
            issues=issues,
        )

    def aggregate_scores(
        self,
        page_scores: list[WikiPageQualityScore],
        tier_map: dict[str, ImportanceTier],
    ) -> dict[str, Any]:
        """Aggregate page scores into module/repo score with tier weighting."""
        tier_weights = {
            ImportanceTier.CORE: 3.0,
            ImportanceTier.STANDARD: 2.0,
            ImportanceTier.SKELETON: 1.0,
        }
        total_weight = 0.0
        weighted_sum = 0.0
        for score in page_scores:
            tier = tier_map.get(score.page_path)
            w = tier_weights.get(tier, 1.0) if tier else 1.0
            weighted_sum += score.overall * w
            total_weight += w
        return {
            "overall": round(weighted_sum / total_weight, 3) if total_weight > 0 else 0,
            "page_count": len(page_scores),
        }

    def select_sample_pages(
        self,
        pages: list[WikiPage],
        tier_map: dict[str, ImportanceTier],
        sample_size: int = 20,
    ) -> list[WikiPage]:
        """Select representative pages for sampled quality evaluation."""
        import random

        core_pages = [p for p in pages if tier_map.get(p.path) == ImportanceTier.CORE]
        standard_pages = [p for p in pages if tier_map.get(p.path) == ImportanceTier.STANDARD]
        sample = list(core_pages)
        remaining = max(0, sample_size - len(sample))
        if remaining > 0 and standard_pages:
            sample.extend(random.sample(standard_pages, min(remaining, len(standard_pages))))
        return sample

    def identify_pages_for_heal(
        self,
        scores: list[WikiPageQualityScore],
        min_score: float = 0.6,
    ) -> list[str]:
        return [s.page_path for s in scores if s.overall < min_score]

    def build_heal_prompt_hint(self, score: WikiPageQualityScore) -> str:
        if not score.issues:
            return ""
        issue_descriptions = {
            "missing_overview": "Add a clear ## Overview section explaining the component's purpose.",
            "missing_components": "Add a ## Key components or ## Methods section listing important members.",
            "missing_relationships": "Add a ## Relationships section showing dependencies and callers.",
            "content_too_short": "Expand the documentation with more detail about behavior and usage.",
            "no_diagrams": "Consider what visual diagram would help explain the architecture.",
        }
        hints = [issue_descriptions.get(i, f"Address: {i}") for i in score.issues]
        return (
            "\n\n## Quality Improvement Instructions\n"
            "The previous version of this documentation was flagged for quality issues. "
            "Please specifically address:\n"
            + "\n".join(f"- {h}" for h in hints)
        )
