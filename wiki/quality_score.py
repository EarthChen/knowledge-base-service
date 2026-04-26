"""Aggregate wiki quality score (coverage, staleness, references, enrichment)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from wiki.coverage_analyzer import WikiCoverageAnalyzer


@dataclass
class QualityFactor:
    name: str
    weight: float
    """Weight in 0-1, sums to 1.0 for the four factors."""
    score: float
    """Per-factor score 0.0-1.0."""


@dataclass
class QualityScoreBreakdown:
    """Serializable quality score (alias for API compatibility)."""

    score: int
    factors: list[QualityFactor]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "factors": [asdict(f) for f in self.factors],
            "details": self.details,
        }


# Backward-compatible name
WikiQualityResult = QualityScoreBreakdown


class WikiQualityScorer:
    """Composite score from coverage (40%), staleness (30%), reference density (20%), enrichment (10%)."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._analyzer = WikiCoverageAnalyzer(store)

    async def compute_score(self, business_id: str) -> WikiQualityResult:
        report = await self._analyzer.analyze(business_id, include_stale=True)
        stats = await self._store.get_entity_coverage_stats(business_id)
        ref_stats = await self._store.get_wiki_reference_and_enrichment_stats(business_id)
        details: dict[str, Any] = {
            "total_entities": stats.get("total_entities", 0),
            "covered_entities": stats.get("covered_entities", 0),
            "stale_page_count": len(report.stale_pages),
            "ref_edge_count": ref_stats.get("ref_edge_count", 0),
            "enriched_pages": ref_stats.get("enriched_pages", 0),
        }

        total = int(stats.get("total_entities", 0) or 0)
        covered = int(stats.get("covered_entities", 0) or 0)

        if total == 0:
            zero_factors: list[QualityFactor] = [
                QualityFactor(name="coverage", weight=0.4, score=0.0),
                QualityFactor(name="staleness", weight=0.3, score=0.0),
                QualityFactor(name="reference_density", weight=0.2, score=0.0),
                QualityFactor(name="annotation_density", weight=0.1, score=0.0),
            ]
            return WikiQualityResult(
                score=0,
                factors=zero_factors,
                details={
                    "total_entities": 0,
                    "covered_entities": 0,
                    "stale_page_count": 0,
                    "ref_edge_count": 0,
                    "enriched_pages": 0,
                },
            )

        coverage_raw = (covered / total) if total > 0 else 0.0

        stale_n = len(report.stale_pages)
        staleness_raw = 1.0 - (stale_n / total if total > 0 else 0.0)
        staleness_raw = max(0.0, min(1.0, staleness_raw))

        ref_edges = int(ref_stats.get("ref_edge_count", 0) or 0)
        if total > 0:
            approx_per_page = ref_edges / total
        else:
            approx_per_page = 0.0
        # Treat ~1.0 outgoing+incoming refs per page (normalized) as "good" (score ~1.0)
        ref_raw = min(1.0, approx_per_page / 1.0) if total > 0 else 0.0

        enr = int(ref_stats.get("enriched_pages", 0) or 0)
        annotation_raw = (enr / total) if total > 0 else 0.0

        factors: list[QualityFactor] = [
            QualityFactor(name="coverage", weight=0.4, score=coverage_raw),
            QualityFactor(name="staleness", weight=0.3, score=staleness_raw),
            QualityFactor(name="reference_density", weight=0.2, score=ref_raw),
            QualityFactor(name="annotation_density", weight=0.1, score=annotation_raw),
        ]
        overall = sum(f.weight * f.score for f in factors)
        score_100 = int(round(max(0.0, min(1.0, overall)) * 100))

        return WikiQualityResult(score=score_100, factors=factors, details=details)
