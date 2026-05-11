"""Tests for compose_domain_agents_node — domain-level Agent orchestration."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.domain_compose import compose_domain_agents_node


class TestComposeDomainAgentsNode:
    @pytest.mark.asyncio
    async def test_produces_pages_for_each_leaf_domain(self):
        state = {
            "domain_tree": [
                {
                    "name": "DomainA",
                    "modules": ["ModA1", "ModA2"],
                    "children": [],
                },
                {
                    "name": "DomainB",
                    "modules": ["ModB1"],
                    "children": [],
                },
            ],
            "module_summaries": {
                "ModA1": "summary A1",
                "ModA2": "summary A2",
                "ModB1": "summary B1",
            },
            "errors": [],
        }
        config = {"configurable": {"llm": MagicMock(), "graph_store": MagicMock()}}

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            instance = AsyncMock()
            instance.generate_with_iterations = AsyncMock(
                return_value=[{"type": "domain_overview", "title": "Domain", "content": "content"}]
            )
            instance.iteration_history = [{"iteration": 0}]
            MockAgent.return_value = instance

            result = await compose_domain_agents_node(state, config)

        assert "pages" in result
        assert len(result["pages"]) == 2

    @pytest.mark.asyncio
    async def test_single_domain_failure_produces_placeholder(self):
        state = {
            "domain_tree": [
                {"name": "GoodDomain", "modules": ["Mod1"], "children": []},
                {"name": "BadDomain", "modules": ["Mod2"], "children": []},
            ],
            "module_summaries": {},
            "errors": [],
        }
        config = {"configurable": {"llm": MagicMock(), "graph_store": MagicMock()}}

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("LLM timeout")
            return [{"type": "domain_overview", "title": "GoodDomain", "content": "ok"}]

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            instance = AsyncMock()
            instance.generate_with_iterations = AsyncMock(side_effect=side_effect)
            instance.iteration_history = []
            MockAgent.return_value = instance

            result = await compose_domain_agents_node(state, config)

        assert len(result["pages"]) == 2
        error_pages = [p for p in result["pages"] if "失败" in p.get("content", "")]
        assert len(error_pages) >= 1

    @pytest.mark.asyncio
    async def test_empty_domain_tree_returns_empty(self):
        state = {"domain_tree": None, "module_summaries": {}, "errors": []}
        config = {"configurable": {"llm": MagicMock(), "graph_store": MagicMock()}}
        result = await compose_domain_agents_node(state, config)
        assert result["pages"] == []
