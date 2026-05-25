"""Tests that agent_error pages are added to pages_to_heal."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def _make_error_page(path: str) -> dict:
    return {
        "path": path,
        "title": "Failed Domain",
        "content": "# Error\n\nAgent failed to generate.",
        "metadata": {"generation_mode": "agent_error"},
    }


class TestAgentErrorPagesHeal:
    @pytest.mark.asyncio
    async def test_agent_error_pages_added_to_heal(self):
        """agent_error pages should be added to pages_to_heal."""
        from wiki.nodes.quality_gate import quality_gate_node

        error_page = _make_error_page("/__domains__/broken/overview")
        normal_page = {
            "path": "/__domains__/good/overview",
            "title": "Good Domain",
            "content": "# Good\n\nWell written content with details.",
            "metadata": {},
        }
        state = {
            "pages": [error_page, normal_page],
            "indexed_modules": {},
            "config": {},
            "heal_attempts": {},
            "heal_cycles": {},
            "_structural_check_cache": {},
        }

        from wiki.quality_evaluator import WikiQualityEvaluator
        with patch.object(WikiQualityEvaluator, "structural_check") as mock_l1:
            mock_result = MagicMock()
            mock_result.overall = 0.9
            mock_result.issues = []
            mock_l1.return_value = mock_result

            with patch("wiki.nodes.quality_gate.verify_citations") as mock_cit:
                mock_cit.return_value = MagicMock(invalid_count=0, invalid_refs=[])
                result = await quality_gate_node(state, {"configurable": {"llm": None}})

        pages_to_heal = result.get("pages_to_heal", [])
        assert error_page["path"] in pages_to_heal

    @pytest.mark.asyncio
    async def test_agent_error_score_zero(self):
        """agent_error pages should still get score 0."""
        from wiki.nodes.quality_gate import quality_gate_node

        error_page = _make_error_page("/__domains__/broken/overview")
        state = {
            "pages": [error_page],
            "indexed_modules": {},
            "config": {},
            "heal_attempts": {},
            "heal_cycles": {},
            "_structural_check_cache": {},
        }

        result = await quality_gate_node(state, {"configurable": {"llm": None}})
        scores = result.get("quality_scores", {})
        assert scores[error_page["path"]]["overall"] == 0.0

    @pytest.mark.asyncio
    async def test_agent_error_max_one_heal_cycle(self):
        """agent_error pages should only get one heal attempt."""
        from wiki.nodes.quality_gate import quality_gate_node

        error_page = _make_error_page("/__domains__/broken/overview")
        state = {
            "pages": [error_page],
            "indexed_modules": {},
            "config": {},
            "heal_attempts": {},
            "heal_cycles": {error_page["path"]: 1},  # Already healed once
            "_structural_check_cache": {},
        }

        result = await quality_gate_node(state, {"configurable": {"llm": None}})
        pages_to_heal = result.get("pages_to_heal", [])
        # Should NOT be added again since already healed once
        assert error_page["path"] not in pages_to_heal
