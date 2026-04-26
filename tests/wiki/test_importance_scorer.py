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


@pytest.mark.asyncio
async def test_score_all(mock_wiki_store):
    result = MagicMock()
    result.result_set = [
        ["uid1", "Class", 1, 100, 10, 5, 3],
        ["uid2", "Module", 1, 500, 5, 2, 10],
        ["uid3", "Class", 1, 20, 1, 1, 0],
    ]
    mock_wiki_store.score_all_entities.return_value = result

    scorer = ImportanceScorer(mock_wiki_store, core_percentile=80, standard_percentile=30)
    tiers = await scorer.score_all("my-repo")

    assert isinstance(tiers, dict)
    assert all(isinstance(v, ImportanceTier) for v in tiers.values())
    assert len(tiers) == 3
