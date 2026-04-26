"""Unit tests for wiki.confidence_scorer."""

import pytest

from wiki.confidence_scorer import (
    DEFAULT_WEIGHTS,
    ConfidenceInputs,
    ConfidenceScorer,
    WeightBundle,
)


def test_confidence_happy_path_matches_spec() -> None:
    scorer = ConfidenceScorer(weights=DEFAULT_WEIGHTS)
    inputs = ConfidenceInputs(
        source_entity_count=3,
        days_since_generated=0,
        up_votes=1,
        down_votes=0,
        inbound_wikilink_count=5,
        contradiction_count=0,
    )
    expected = 0.3 * 1.0 + 0.25 * 1.0 + 0.25 * 0.5 + 0.20 * 1.0
    assert scorer.compute(inputs) == pytest.approx(expected, rel=1e-5)


def test_contradiction_penalty_reduces_score() -> None:
    scorer = ConfidenceScorer(weights=DEFAULT_WEIGHTS)
    base = ConfidenceInputs(3, 0, 0, 0, 5, 0)
    with_pen = ConfidenceInputs(3, 0, 0, 0, 5, 2)
    assert scorer.compute(with_pen) < scorer.compute(base)


@pytest.mark.parametrize(
    "days",
    [0, 45, 90, 120],
)
def test_freshness_drives_score_when_other_factors_zero(days: int) -> None:
    """Source, feedback, refs, and penalty are zero; score is w2 * freshness only."""
    scorer = ConfidenceScorer(weights=DEFAULT_WEIGHTS)
    inputs = ConfidenceInputs(0, days, 0, 0, 0, 0)
    out = scorer.compute(inputs)
    fresh = max(1.0 - days / 90, 0.0)
    assert out == pytest.approx(0.25 * fresh, rel=1e-5)


@pytest.mark.parametrize(
    "source_n,source_term",
    [
        (0, 0.0),
        (1, 0.3 * (1.0 / 3)),
        (3, 0.3 * 1.0),
        (10, 0.3 * 1.0),
    ],
)
def test_source_cap(source_n: int, source_term: float) -> None:
    scorer = ConfidenceScorer(weights=DEFAULT_WEIGHTS)
    # stale page: 90d -> fresh=0, no feedback, no refs
    inputs = ConfidenceInputs(source_n, 90, 0, 0, 0, 0)
    assert scorer.compute(inputs) == pytest.approx(source_term, rel=1e-5)


def test_clamps_to_unit_interval() -> None:
    w = WeightBundle(1.0, 0.0, 0.0, 0.0, 0.0)
    s = ConfidenceScorer(weights=w)
    assert s.compute(ConfidenceInputs(0, 0, 0, 0, 0, 0)) == 0.0
    assert s.compute(ConfidenceInputs(9, 0, 0, 0, 0, 0)) == 1.0  # 9/3 = 3 -> cap 1


def test_custom_weights() -> None:
    w = WeightBundle(0.5, 0.5, 0.0, 0.0, 0.0)
    s = ConfidenceScorer(weights=w)
    # source=0, days=0 -> fresh=1, half each
    val = s.compute(ConfidenceInputs(0, 0, 0, 0, 0, 0))
    assert val == pytest.approx(0.5, rel=1e-5)
