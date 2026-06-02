"""Test that agent_error pages participate in healing (configurable max cycles)."""
from __future__ import annotations

import pytest

from wiki.nodes.quality_gate import quality_gate_node


@pytest.mark.asyncio
async def test_agent_error_pages_added_to_heal_once(monkeypatch):
    """Pages with generation_mode=agent_error should enter pages_to_heal once."""
    def _fake_settings():
        wiki = type("W", (), {
            "quality_gate_levels": "L1",
            "heal_l2_threshold": 0.0,
            "agent_error_heal_max_cycles": 3,
        })()
        return type("S", (), {"wiki": wiki})()

    monkeypatch.setattr("wiki.nodes.quality_gate.get_settings", _fake_settings)

    error_page = {
        "path": "/wiki/broken-domain",
        "title": "Broken Domain",
        "page_type": "topic",
        "content": "Error generating page",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "agent_error"},
    }
    state = {
        "pages": [error_page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }
    result = await quality_gate_node(state, {"configurable": {}})
    assert "/wiki/broken-domain" in result.get("pages_to_heal", [])
    scores = result.get("quality_scores", {})
    assert scores.get("/wiki/broken-domain", {}).get("skipped_reason") == "agent_error"


@pytest.mark.asyncio
async def test_agent_error_pages_not_rehealed_after_max_cycles(monkeypatch):
    """agent_error pages should not re-enter pages_to_heal after max heal cycles."""
    def _fake_settings():
        wiki = type("W", (), {
            "quality_gate_levels": "L1",
            "heal_l2_threshold": 0.0,
            "agent_error_heal_max_cycles": 3,
        })()
        return type("S", (), {"wiki": wiki})()

    monkeypatch.setattr("wiki.nodes.quality_gate.get_settings", _fake_settings)

    error_page = {
        "path": "/wiki/broken-domain",
        "title": "Broken Domain",
        "page_type": "topic",
        "content": "Error generating page",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "agent_error"},
    }
    state = {
        "pages": [error_page],
        "heal_attempts": {},
        "heal_cycles": {"/wiki/broken-domain": 3},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }
    result = await quality_gate_node(state, {"configurable": {}})
    assert "/wiki/broken-domain" not in result.get("pages_to_heal", [])


def _fake_settings(agent_error_heal_max_cycles: int = 3):
    wiki = type("W", (), {
        "quality_gate_levels": "L1",
        "heal_l2_threshold": 0.0,
        "agent_error_heal_max_cycles": agent_error_heal_max_cycles,
    })()
    return type("S", (), {"wiki": wiki})()


def _error_fallback_page(path: str = "/wiki/fallback-domain") -> dict:
    return {
        "path": path,
        "title": "Fallback Domain",
        "page_type": "topic",
        "content": "Compose failed; skeleton produced",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "error_fallback"},
    }


class TestQualityGateErrorFallback:
    """error_fallback pages should be treated same as agent_error for heal cycles."""

    @pytest.mark.asyncio
    async def test_error_fallback_pages_trigger_heal(self, monkeypatch):
        """Pages with generation_mode=error_fallback should enter pages_to_heal."""
        monkeypatch.setattr(
            "wiki.nodes.quality_gate.get_settings",
            lambda: _fake_settings(agent_error_heal_max_cycles=3),
        )

        state = {
            "pages": [_error_fallback_page()],
            "heal_attempts": {},
            "heal_cycles": {},
            "config": {"importance_tiers": {}},
            "_structural_check_cache": {},
        }
        result = await quality_gate_node(state, {"configurable": {}})
        assert "/wiki/fallback-domain" in result.get("pages_to_heal", [])
        scores = result.get("quality_scores", {})
        assert scores.get("/wiki/fallback-domain", {}).get("skipped_reason") == "error_fallback"

    @pytest.mark.asyncio
    async def test_error_fallback_uses_agent_error_heal_max_cycles(self, monkeypatch):
        """error_fallback pages use agent_error_heal_max_cycles, not default tier max."""
        monkeypatch.setattr(
            "wiki.nodes.quality_gate.get_settings",
            lambda: _fake_settings(agent_error_heal_max_cycles=3),
        )

        state = {
            "pages": [_error_fallback_page()],
            "heal_attempts": {},
            "heal_cycles": {"/wiki/fallback-domain": 1},
            "config": {"importance_tiers": {}},
            "_structural_check_cache": {},
        }
        result = await quality_gate_node(state, {"configurable": {}})
        assert "/wiki/fallback-domain" in result.get("pages_to_heal", [])

    @pytest.mark.asyncio
    async def test_error_fallback_at_max_cycles_stops_healing(self, monkeypatch):
        """error_fallback pages should not re-enter pages_to_heal after max heal cycles."""
        monkeypatch.setattr(
            "wiki.nodes.quality_gate.get_settings",
            lambda: _fake_settings(agent_error_heal_max_cycles=3),
        )

        state = {
            "pages": [_error_fallback_page()],
            "heal_attempts": {},
            "heal_cycles": {"/wiki/fallback-domain": 3},
            "config": {"importance_tiers": {}},
            "_structural_check_cache": {},
        }
        result = await quality_gate_node(state, {"configurable": {}})
        assert "/wiki/fallback-domain" not in result.get("pages_to_heal", [])
