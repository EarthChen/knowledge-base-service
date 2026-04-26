"""Feature flags for SP5 claim supersession."""

from config import WikiConfig


def test_supersession_tracking_default_off() -> None:
    assert WikiConfig().supersession_tracking_enabled is False
