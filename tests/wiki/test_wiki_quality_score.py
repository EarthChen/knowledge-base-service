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
            "total_modules": 10,
            "covered_modules": 8,
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
async def test_page_level_factors_use_total_pages_denominator() -> None:
    """Staleness, reference density, and enrichment use total_pages; coverage uses indexed modules."""
    store = MagicMock()
    store.get_entity_coverage_stats = AsyncMock(
        return_value={
            "total_modules": 20,
            "covered_modules": 10,
        },
    )
    store.get_knowledge_gaps = AsyncMock(return_value=[])
    store.get_stale_wiki_pages = AsyncMock(return_value=[])
    store.get_wiki_reference_and_enrichment_stats = AsyncMock(
        return_value={"ref_edge_count": 5, "total_pages": 10, "enriched_pages": 2},
    )

    r = await WikiQualityScorer(store).compute_score("biz")

    cov = next(f for f in r.factors if f.name == "coverage")
    assert abs(cov.score - 0.5) < 0.01  # 10/20 modules
    ref = next(f for f in r.factors if f.name == "reference_density")
    assert abs(ref.score - 0.5) < 0.01  # 5 ref edges / 10 pages, not / 20 entities
    ann = next(f for f in r.factors if f.name == "annotation_density")
    assert abs(ann.score - 0.2) < 0.01  # 2 enriched / 10 pages, not / 20 entities
    assert r.details.get("total_pages") == 10


@pytest.mark.asyncio
async def test_empty_business_zeroes_gracefully() -> None:
    store = MagicMock()
    store.get_entity_coverage_stats = AsyncMock(
        return_value={
            "total_modules": 0,
            "covered_modules": 0,
        },
    )
    store.get_knowledge_gaps = AsyncMock(return_value=[])
    store.get_stale_wiki_pages = AsyncMock(return_value=[])
    store.get_wiki_reference_and_enrichment_stats = AsyncMock(
        return_value={"ref_edge_count": 0, "total_pages": 0, "enriched_pages": 0},
    )

    r = await WikiQualityScorer(store).compute_score("ghost")
    assert r.score == 0
