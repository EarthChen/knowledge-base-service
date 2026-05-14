"""Wiki coverage analysis — identifies documentation gaps and stale content."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoverageReport:
    """Module-based wiki coverage report."""

    total_modules: int
    """Total indexed code modules in business-bound repos."""

    covered_modules: int
    """Modules with business_domain assigned (documented by wiki)."""

    stale_pages: list[dict[str, Any]] = field(default_factory=list)
    """Pages whose source entities changed after wiki generation."""

    knowledge_gaps: list[dict[str, Any]] = field(default_factory=list)
    """Entities with weak documentation relative to graph importance."""

    @property
    def coverage_percentage(self) -> float:
        """Percentage of documented modules (0-100 scale)."""
        if self.total_modules == 0:
            return 0.0
        return round(self.covered_modules / self.total_modules * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_modules": self.total_modules,
            "covered_modules": self.covered_modules,
            "coverage_percentage": self.coverage_percentage,
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

        return CoverageReport(
            total_modules=stats.get("total_modules", 0),
            covered_modules=stats.get("covered_modules", 0),
            stale_pages=stale_raw,
            knowledge_gaps=[
                {"entity": g["entity_name"], "in_degree": g["in_degree"], "wiki_tier": g.get("wiki_tier")}
                for g in gaps_raw
            ],
        )

    async def detect_stale_pages(self, business_id: str) -> list[dict[str, Any]]:
        return await self._store.get_stale_wiki_pages(business_id)
