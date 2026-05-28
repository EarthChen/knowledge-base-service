"""Tests for tier-based DomainDocAgent iteration caps."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import AppWikiFlags
from wiki.domain_doc_agent import DomainDocAgent
from wiki.models import ImportanceTier
from wiki.nodes.domain_compose import _explore_limits_for_domain, _max_iterations_for_domain
from wiki.nodes.tier_utils import tier_for_module_count


class TestTierForModuleCount:
    def test_core_tier_for_large_domain(self):
        assert tier_for_module_count(15) == "core"
        assert tier_for_module_count(20) == "core"

    def test_standard_tier_for_medium_domain(self):
        assert tier_for_module_count(2) == "standard"
        assert tier_for_module_count(14) == "standard"

    def test_skeleton_tier_for_small_domain(self):
        assert tier_for_module_count(1) == "skeleton"
        assert tier_for_module_count(0) == "skeleton"


class TestDomainAgentMaxIterations:
    def test_config_defaults(self):
        cfg = AppWikiFlags()
        assert cfg.domain_agent_max_iterations_core == 20
        assert cfg.domain_agent_max_iterations_standard == 8
        assert cfg.domain_agent_max_iterations_skeleton == 3

    def test_config_override(self):
        cfg = AppWikiFlags(
            domain_agent_max_iterations_core=12,
            domain_agent_max_iterations_standard=5,
            domain_agent_max_iterations_skeleton=1,
        )
        assert cfg.domain_agent_max_iterations_core == 12
        assert cfg.domain_agent_max_iterations_standard == 5
        assert cfg.domain_agent_max_iterations_skeleton == 1

    def test_max_iterations_mapping(self):
        wiki_cfg = AppWikiFlags()
        with patch("wiki.nodes.domain_compose.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(wiki=wiki_cfg)

            core_domain = {"name": "auth", "modules": [f"m{i}" for i in range(15)]}
            standard_domain = {"name": "billing", "modules": ["m1", "m2"]}
            skeleton_domain = {"name": "util", "modules": ["m1"]}

            assert _max_iterations_for_domain(core_domain, {"config": {}}) == 20
            assert _max_iterations_for_domain(standard_domain, {"config": {}}) == 8
            assert _max_iterations_for_domain(skeleton_domain, {"config": {}}) == 3

    @pytest.mark.asyncio
    async def test_compose_passes_tier_max_iterations_to_agent(self):
        from wiki.nodes.domain_compose import compose_domain_agents_node

        state = {
            "domain_tree": [
                {"name": "CoreDomain", "modules": [f"M{i}" for i in range(15)], "children": []},
                {"name": "StandardDomain", "modules": ["M1", "M2"], "children": []},
                {"name": "SkeletonDomain", "modules": ["M3"], "children": []},
            ],
            "module_summaries": {},
            "errors": [],
            "config": {},
        }
        mock_gs = AsyncMock()
        mock_gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        config = {"configurable": {"llm": MagicMock(), "graph_store": mock_gs}}

        captured: list[int] = []

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            def make_agent(**kwargs):
                captured.append(kwargs.get("max_iterations"))
                instance = AsyncMock()
                instance.generate_with_iterations = AsyncMock(
                    return_value=[{"type": "domain_overview", "title": "D", "content": "c"}]
                )
                instance.iteration_history = []
                return instance

            MockAgent.side_effect = make_agent

            await compose_domain_agents_node(state, config)

        assert sorted(captured) == sorted([20, 8, 3])

    @pytest.mark.asyncio
    async def test_config_importance_tiers_override_module_count(self):
        from wiki.nodes.domain_compose import compose_domain_agents_node
        from wiki.path_conventions import domain_overview_path

        domain_name = "OverrideDomain"
        state = {
            "domain_tree": [
                {"name": domain_name, "modules": [f"M{i}" for i in range(15)], "children": []},
            ],
            "module_summaries": {},
            "errors": [],
            "config": {
                "importance_tiers": {
                    domain_overview_path(domain_name): ImportanceTier.SKELETON.value,
                },
            },
        }
        mock_gs = AsyncMock()
        mock_gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        config = {"configurable": {"llm": MagicMock(), "graph_store": mock_gs}}

        captured: list[int] = []

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            def make_agent(**kwargs):
                captured.append(kwargs.get("max_iterations"))
                instance = AsyncMock()
                instance.generate_with_iterations = AsyncMock(
                    return_value=[{"type": "domain_overview", "title": "D", "content": "c"}]
                )
                instance.iteration_history = []
                return instance

            MockAgent.side_effect = make_agent

            await compose_domain_agents_node(state, config)

        assert captured == [3]


class TestDomainAgentExploreLimits:
    def test_skeleton_agent_uses_reduced_explore_rounds(self):
        agent = DomainDocAgent(
            "util",
            MagicMock(),
            MagicMock(),
            explore_max_rounds=2,
            explore_max_tool_calls=8,
        )
        assert agent._page_agent.max_rounds == 2
        assert agent._page_agent.max_tool_calls == 8

    def test_core_agent_uses_config_default_explore_rounds(self):
        agent = DomainDocAgent("auth", MagicMock(), MagicMock())
        assert agent._page_agent.max_rounds == 8
        assert agent._page_agent.max_tool_calls == 30

    def test_explore_limits_mapping(self):
        wiki_cfg = AppWikiFlags()
        with patch("wiki.nodes.domain_compose.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(wiki=wiki_cfg)

            core_domain = {"name": "auth", "modules": [f"m{i}" for i in range(15)]}
            standard_domain = {"name": "billing", "modules": ["m1", "m2"]}
            skeleton_domain = {"name": "util", "modules": ["m1"]}

            assert _explore_limits_for_domain(core_domain, {"config": {}}) == (None, None)
            assert _explore_limits_for_domain(standard_domain, {"config": {}}) == (5, 20)
            assert _explore_limits_for_domain(skeleton_domain, {"config": {}}) == (2, 8)

    @pytest.mark.asyncio
    async def test_compose_passes_tier_explore_limits_to_agent(self):
        from wiki.nodes.domain_compose import compose_domain_agents_node

        state = {
            "domain_tree": [
                {"name": "CoreDomain", "modules": [f"M{i}" for i in range(15)], "children": []},
                {"name": "StandardDomain", "modules": ["M1", "M2"], "children": []},
                {"name": "SkeletonDomain", "modules": ["M3"], "children": []},
            ],
            "module_summaries": {},
            "errors": [],
            "config": {},
        }
        mock_gs = AsyncMock()
        mock_gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        config = {"configurable": {"llm": MagicMock(), "graph_store": mock_gs}}

        captured_rounds: list[int | None] = []
        captured_calls: list[int | None] = []

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            def make_agent(**kwargs):
                captured_rounds.append(kwargs.get("explore_max_rounds"))
                captured_calls.append(kwargs.get("explore_max_tool_calls"))
                instance = AsyncMock()
                instance.generate_with_iterations = AsyncMock(
                    return_value=[{"type": "domain_overview", "title": "D", "content": "c"}]
                )
                instance.iteration_history = []
                return instance

            MockAgent.side_effect = make_agent

            await compose_domain_agents_node(state, config)

        # Core tier returns None; F11d fills scaled defaults (8 rounds / 30 calls) for 15 modules.
        assert set(captured_rounds) == {8, 2, 5}
        assert set(captured_calls) == {30, 8, 20}
