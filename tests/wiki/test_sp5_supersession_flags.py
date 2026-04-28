"""Feature flags for SP5 claim supersession."""

from config import AppWikiFlags


def test_supersession_tracking_default_on() -> None:
    assert AppWikiFlags().supersession_tracking_enabled is True
