"""Wiki coverage analysis — identifies documentation gaps and stale content."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoverageReport:
    """Coverage analysis result for a business wiki."""
    total_entities: int
    covered_entities: int
    core_coverage: float
    standard_coverage: float
    stale_pages: list[dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def coverage_percentage(self) -> float:
        if self.total_entities == 0:
            return 0.0
        return round(self.covered_entities / self.total_entities * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entities": self.total_entities,
            "covered_entities": self.covered_entities,
            "coverage_percentage": self.coverage_percentage,
            "core_coverage": self.core_coverage,
            "standard_coverage": self.standard_coverage,
            "stale_pages": self.stale_pages,
            "stale_page_count": len(self.stale_pages),
            "knowledge_gaps": self.knowledge_gaps,
            "knowledge_gap_count": len(self.knowledge_gaps),
        }


class WikiCoverageAnalyzer:
    """Analyzes wiki documentation coverage and identifies quality issues."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def analyze(
        self, business_id: str, *, include_stale: bool = True,
    ) -> CoverageReport:
        stats = await self._store.get_entity_coverage_stats(business_id)
        gaps_raw = await self._store.get_knowledge_gaps(business_id)
        stale_raw = (
            await self._store.get_stale_wiki_pages(business_id)
            if include_stale
            else []
        )

        total = stats.get("total_entities", 0)
        core = stats.get("core_total", 0)
        standard = stats.get("standard_total", 0)

        core_coverage = core / total if total > 0 else 0.0
        standard_coverage = (core + standard) / total if total > 0 else 0.0

        return CoverageReport(
            total_entities=total,
            covered_entities=stats.get("covered_entities", 0),
            core_coverage=round(core_coverage, 2),
            standard_coverage=round(standard_coverage, 2),
            stale_pages=stale_raw,
            knowledge_gaps=[
                {"entity": g["entity_name"], "in_degree": g["in_degree"], "wiki_tier": g.get("wiki_tier")}
                for g in gaps_raw
            ],
        )

    async def detect_stale_pages(self, business_id: str) -> list[dict[str, Any]]:
        return await self._store.get_stale_wiki_pages(business_id)
