"""Feature flags for SP4 contradiction detection."""

from core.config import AppWikiFlags


def test_contradiction_detection_default_on() -> None:
    assert AppWikiFlags().contradiction_detection_enabled is True


def test_contradiction_similarity_default() -> None:
    assert AppWikiFlags().contradiction_similarity_threshold == 0.75
