import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.importance_scorer import ImportanceScorer
from wiki.models import ImportanceTier


@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.score_all_entities = AsyncMock()
    return store


def test_compute_score_class():
    scorer = ImportanceScorer(MagicMock(), core_percentile=80, standard_percentile=30)
    score = scorer.compute_score(
        label="Class",
        in_degree=10,
        out_degree=5,
        children_count=3,
        code_lines=100,
        has_subclasses=True,
    )
    expected = (10 * 3) + (5 * 1) + (3 * 2) + math.log2(101) * 2 + 3
    assert abs(score - expected) < 0.01


def test_compute_score_module():
    scorer = ImportanceScorer(MagicMock(), core_percentile=80, standard_percentile=30)
    score = scorer.compute_score(
        label="Module",
        in_degree=5,
        out_degree=2,
        children_count=10,
        code_lines=500,
        has_subclasses=False,
    )
    expected = (5 * 3) + (2 * 1) + (10 * 2) + math.log2(501) * 2 + 5
    assert abs(score - expected) < 0.01


def test_classify_by_percentile():
    scorer = ImportanceScorer(MagicMock(), core_percentile=80, standard_percentile=30)
    scores = {"a": 100, "b": 80, "c": 60, "d": 40, "e": 20}
    result = scorer.classify_by_percentile(scores)
    assert result["a"] == ImportanceTier.CORE
    assert result["e"] == ImportanceTier.SKELETON


# --- G-T2: cross_domain_callers tests ---


def test_cross_domain_callers_boosts_score():
    """Entities called from multiple business domains should score higher."""
    scorer = ImportanceScorer(wiki_store=None)
    base_score = scorer.compute_score(
        label="Module",
        in_degree=5,
        out_degree=2,
        children_count=3,
        code_lines=100,
        has_subclasses=False,
        cross_domain_callers=0,
    )
    boosted_score = scorer.compute_score(
        label="Module",
        in_degree=5,
        out_degree=2,
        children_count=3,
        code_lines=100,
        has_subclasses=False,
        cross_domain_callers=3,
    )
    assert boosted_score > base_score
    assert boosted_score - base_score == 3 * 4  # weight is 4


def test_zero_cross_domain_no_change():
    """Zero cross-domain callers should not change the score."""
    scorer = ImportanceScorer(wiki_store=None)
    score_without = scorer.compute_score(
        label="Class",
        in_degree=10,
        out_degree=5,
        children_count=4,
        code_lines=200,
        has_subclasses=True,
    )
    score_with_zero = scorer.compute_score(
        label="Class",
        in_degree=10,
        out_degree=5,
        children_count=4,
        code_lines=200,
        has_subclasses=True,
        cross_domain_callers=0,
    )
    assert score_without == score_with_zero


@pytest.mark.asyncio
async def test_score_all_with_cross_domain():
    """Full score_all flow should parse the 9th column (cross_domain_callers)."""
    mock_store = AsyncMock()
    mock_result = MagicMock()
    # 9 columns: uid, label, start_line, end_line, in_deg, out_deg, children, subclass, cross_domain
    mock_result.result_set = [
        ("uid_a", "Module", 0, 100, 5, 2, 3, 0, 3),  # cross_domain=3
        ("uid_b", "Module", 0, 50, 2, 1, 1, 0, 0),  # cross_domain=0
    ]
    mock_store.score_all_entities = AsyncMock(return_value=mock_result)

    scorer = ImportanceScorer(wiki_store=mock_store)
    tiers = await scorer.score_all("test-repo")

    assert "uid_a" in tiers
    assert "uid_b" in tiers
    # uid_a with cross_domain=3 should score higher -> more likely CORE
    # (exact tier depends on percentile, but with only 2 entities, uid_a should be CORE)
    assert tiers["uid_a"] == ImportanceTier.CORE


@pytest.mark.asyncio
async def test_score_all(mock_wiki_store):
    result = MagicMock()
    result.result_set = [
        ["uid1", "Class", 1, 100, 10, 5, 3, 1, 0],
        ["uid2", "Module", 1, 500, 5, 2, 10, 0, 0],
        ["uid3", "Class", 1, 20, 1, 1, 0, 0, 0],
    ]
    mock_wiki_store.score_all_entities.return_value = result

    scorer = ImportanceScorer(mock_wiki_store, core_percentile=80, standard_percentile=30)
    tiers = await scorer.score_all("my-repo")

    assert isinstance(tiers, dict)
    assert all(isinstance(v, ImportanceTier) for v in tiers.values())
    assert len(tiers) == 3
