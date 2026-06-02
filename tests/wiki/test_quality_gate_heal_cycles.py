from __future__ import annotations

from unittest.mock import patch

import pytest


class TestAgentErrorHealCycles:
    """Verify agent_error pages get up to 3 heal cycles."""

    def _build_agent_error_page(self, path: str = "test-domain/index") -> dict:
        return {
            "page_type": "domain_overview",
            "path": path,
            "title": "Test Domain",
            "content": "> ⚠️ 文档生成失败: TimeoutError: timeout/cancelled\n\n## 域内模块\n\n- mod_a\n- mod_b",
            "metadata": {"generation_mode": "agent_error"},
        }

    @pytest.mark.asyncio
    async def test_agent_error_healed_up_to_max_cycles(self):
        """Agent error pages should be queued for healing if cycles < max."""
        from wiki.nodes.quality_gate import quality_gate_node

        page = self._build_agent_error_page()
        state = {
            "pages": [page],
            "heal_cycles": {"test-domain/index": 2},  # already healed twice
            "repo_id": "test-repo",
            "config": {},
        }
        with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
            mock_settings.return_value.wiki.agent_error_heal_max_cycles = 3
            # With 2 cycles done and max=3, it should still queue for healing
            result = await quality_gate_node(state)
            pages_to_heal = result.get("pages_to_heal", [])
            assert "test-domain/index" in pages_to_heal

    @pytest.mark.asyncio
    async def test_agent_error_not_healed_after_max_cycles(self):
        """Agent error pages should NOT be queued after reaching max cycles."""
        from wiki.nodes.quality_gate import quality_gate_node

        page = self._build_agent_error_page()
        state = {
            "pages": [page],
            "heal_cycles": {"test-domain/index": 3},  # already healed max times
            "repo_id": "test-repo",
            "config": {},
        }
        with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
            mock_settings.return_value.wiki.agent_error_heal_max_cycles = 3
            result = await quality_gate_node(state)
            pages_to_heal = result.get("pages_to_heal", [])
            assert "test-domain/index" not in pages_to_heal

    def test_default_config_value_is_3(self):
        """The default value for agent_error_heal_max_cycles should be 3."""
        from core.config import get_settings

        settings = get_settings()
        assert settings.wiki.agent_error_heal_max_cycles == 3
