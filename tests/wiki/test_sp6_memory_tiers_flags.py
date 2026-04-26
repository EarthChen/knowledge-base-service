"""SP6: memory tier consolidation feature flag on application WikiConfig."""

from __future__ import annotations

from config import WikiConfig


def test_memory_tiers_enabled_defaults_false() -> None:
    assert WikiConfig().memory_tiers_enabled is False


def test_memory_tiers_enabled_can_enable() -> None:
    c = WikiConfig()
    c2 = c.model_copy(update={"memory_tiers_enabled": True})
    assert c2.memory_tiers_enabled is True
