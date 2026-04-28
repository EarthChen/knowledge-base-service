"""SP3: confidence scoring feature flags on application AppWikiFlags."""

from __future__ import annotations

from config import AppWikiFlags


def test_confidence_scoring_default_on() -> None:
    assert AppWikiFlags().confidence_scoring_enabled is True


def test_confidence_weights_match_spec_defaults() -> None:
    c = AppWikiFlags()
    assert c.confidence_weight_w1 == 0.30
    assert c.confidence_weight_w2 == 0.25
    assert c.confidence_weight_w3 == 0.25
    assert c.confidence_weight_w4 == 0.20
    assert c.confidence_weight_w5 == 1.0
