"""SP6: memory tier consolidation feature flag on application AppWikiFlags."""

from __future__ import annotations

from config import AppWikiFlags


def test_memory_tiers_enabled_defaults_true() -> None:
    assert AppWikiFlags().memory_tiers_enabled is True


def test_memory_tiers_enabled_can_disable() -> None:
    c = AppWikiFlags()
    c2 = c.model_copy(update={"memory_tiers_enabled": False})
    assert c2.memory_tiers_enabled is False
