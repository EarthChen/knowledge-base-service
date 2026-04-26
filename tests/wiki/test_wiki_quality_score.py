"""Tests for wiki.quality_score.WikiQualityScorer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.quality_score import WikiQualityScorer


@pytest.mark.asyncio
async def test_compute_score_weighted_100_scale() -> None:
    store = MagicMock()
    store.get_entity_coverage_stats = AsyncMock(
        return_value={
            "total_entities": 10,
            "covered_entities": 8,
            "core_total": 3,
            "standard_total": 5,
            "skeleton_total": 2,
        },
    )
    store.get_knowledge_gaps = AsyncMock(return_value=[])
    store.get_stale_wiki_pages = AsyncMock(return_value=[])
    store.get_wiki_reference_and_enrichment_stats = AsyncMock(
        return_value={"ref_edge_count": 5, "total_pages": 10, "enriched_pages": 4},
    )

    scorer = WikiQualityScorer(store)
    r = await scorer.compute_score("default")

    assert 0 <= r.score <= 100
    assert len(r.factors) == 4
    names = {f.name for f in r.factors}
    assert names == {"coverage", "staleness", "reference_density", "annotation_density"}
    cov = next(f for f in r.factors if f.name == "coverage")
    assert abs(cov.score - 0.8) < 0.01  # 8/10


@pytest.mark.asyncio
async def test_empty_business_zeroes_gracefully() -> None:
    store = MagicMock()
    store.get_entity_coverage_stats = AsyncMock(
        return_value={
            "total_entities": 0,
            "covered_entities": 0,
            "core_total": 0,
            "standard_total": 0,
            "skeleton_total": 0,
        },
    )
    store.get_knowledge_gaps = AsyncMock(return_value=[])
    store.get_stale_wiki_pages = AsyncMock(return_value=[])
    store.get_wiki_reference_and_enrichment_stats = AsyncMock(
        return_value={"ref_edge_count": 0, "total_pages": 0, "enriched_pages": 0},
    )

    r = await WikiQualityScorer(store).compute_score("ghost")
    assert r.score == 0
