"""Wiki page quality evaluation: structural checks, LLM-as-Judge, aggregation."""

from __future__ import annotations

import json
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
            raw = await self._llm.generate(prompt, system="You are a documentation quality evaluator. Output valid JSON only.")
            result = json.loads(raw.strip().strip("```json").strip("```"))
        except (json.JSONDecodeError, Exception):
            log.warning("llm_judge_parse_failed", page=page.path, exc_info=True)
            return self.structural_check(page)

        completeness = max(0.0, min(1.0, float(result.get("completeness", 0))))
        helpfulness = max(0.0, min(1.0, float(result.get("helpfulness", 0))))
        truthfulness = max(0.0, min(1.0, float(result.get("truthfulness", 0))))

        return WikiPageQualityScore(
            page_path=page.path,
            completeness=completeness,
            helpfulness=helpfulness,
            truthfulness=truthfulness,
            overall=round((completeness + helpfulness + truthfulness) / 3, 3),
            issues=result.get("issues", []),
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
