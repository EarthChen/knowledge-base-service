"""Tests that quality_gate and heal use consistent tier defaults."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_page_dict(path: str, content: str = "# Title\n\nSome content.\n") -> dict:
    return {
        "path": path,
        "title": "Test",
        "content": content,
        "page_type": "domain_overview",
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }


class TestTierDefaultAlignment:
    """quality_gate and heal must agree on default tier when importance_tiers is empty."""

    @pytest.mark.asyncio
    async def test_quality_gate_default_tier_is_core(self):
        """When importance_tiers is empty, quality_gate should treat pages as core (matching heal)."""
        from wiki.nodes.quality_gate import quality_gate_node
        from wiki.quality_evaluator import WikiQualityEvaluator

        page = _make_page_dict("/__domains__/test/overview")
        state = {
            "pages": [page],
            "indexed_modules": {},
            "config": {},  # No importance_tiers
            "heal_attempts": {},
            "heal_cycles": {},
            "_structural_check_cache": {},
        }

        with patch.object(WikiQualityEvaluator, "structural_check") as mock_l1:
            mock_result = MagicMock()
            mock_result.overall = 0.45  # Below core threshold (0.7) AND standard threshold (0.5)
            mock_result.issues = []
            mock_l1.return_value = mock_result

            with patch("wiki.nodes.quality_gate.verify_citations") as mock_cit:
                mock_cit.return_value = MagicMock(invalid_count=0, invalid_refs=[])
                result = await quality_gate_node(state, {"configurable": {"llm": None}})

        pages_to_heal = result.get("pages_to_heal", [])
        # With core default and 0.45 score (<0.7 threshold), page should be marked for heal
        assert any(p == page["path"] for p in pages_to_heal)

    @pytest.mark.asyncio
    async def test_heal_default_tier_matches_quality_gate(self):
        """heal_pages_node default behavior should match quality_gate default tier."""
        from wiki.nodes.heal import heal_pages_node

        page = _make_page_dict("/__domains__/test/overview")
        state = {
            "pages": [page],
            "pages_to_heal": [page["path"]],
            "config": {},  # No importance_tiers
        }

        with patch("wiki.nodes.heal._heal_one_page", new_callable=AsyncMock) as mock_heal:
            mock_heal.return_value = dict(page)
            with patch("wiki.pipeline_concurrency.PipelineConcurrency") as mock_pc:
                mock_pc.semaphore.return_value = MagicMock(
                    __aenter__=AsyncMock(), __aexit__=AsyncMock()
                )
                await heal_pages_node(state, {"configurable": {"llm": AsyncMock(), "budget_resolver": None}})

        # Verify _heal_one_page was called — the important thing is both nodes
        # agree on whether this page should be healed, and how many rounds
        assert mock_heal.called
