"""Feature flags for SP4 contradiction detection."""

from config import WikiConfig


def test_contradiction_detection_default_off() -> None:
    assert WikiConfig().contradiction_detection_enabled is False


def test_contradiction_similarity_default() -> None:
    assert WikiConfig().contradiction_similarity_threshold == 0.75
