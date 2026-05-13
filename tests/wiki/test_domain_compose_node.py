"""Tests for compose_domain_agents_node — domain-level Agent orchestration."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.domain_compose import _make_error_placeholder, compose_domain_agents_node


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

    @pytest.mark.asyncio
    async def test_passes_module_tree_into_build_baseline(self):
        """Graph decompose produces module_tree; compose should inject it into baseline."""
        mt = [{"canonical_key": "M1", "children": [{"canonical_key": "Ext", "children": []}]}]
        state = {
            "domain_tree": [{"name": "D1", "modules": ["M1"], "children": []}],
            "module_summaries": {},
            "module_tree": mt,
            "errors": [],
        }
        config = {"configurable": {"llm": MagicMock(), "graph_store": MagicMock()}}

        with (
            patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent,
            patch("wiki.nodes.domain_compose._build_baseline") as mock_baseline,
        ):
            mock_baseline.return_value = "## D1 context"
            instance = AsyncMock()
            instance.generate_with_iterations = AsyncMock(
                return_value=[{"type": "domain_overview", "title": "D1", "content": "c"}]
            )
            instance.iteration_history = []
            MockAgent.return_value = instance

            await compose_domain_agents_node(state, config)

        mock_baseline.assert_called_once()
        assert mock_baseline.call_args.kwargs.get("module_tree") == mt

    @pytest.mark.asyncio
    async def test_repo_path_passed_to_agent(self):
        state = {
            "domain_tree": [{"name": "D1", "modules": ["M1"], "children": []}],
            "module_summaries": {},
            "errors": [],
        }
        config = {
            "configurable": {
                "llm": MagicMock(),
                "graph_store": MagicMock(),
                "repo_paths": {"my-repo": "/tmp/repos/my-repo"},
            },
        }

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            instance = AsyncMock()
            instance.generate_with_iterations = AsyncMock(
                return_value=[{"type": "domain_overview", "title": "D1", "content": "c"}]
            )
            instance.iteration_history = []
            MockAgent.return_value = instance

            await compose_domain_agents_node(state, config)

        MockAgent.assert_called_once()
        assert MockAgent.call_args.kwargs.get("repo_path") == "/tmp/repos/my-repo"


def test_error_placeholder_uses_domain_overview_path():
    domain = {"name": "挚友关系管理", "modules": ["ModA"]}
    page = _make_error_placeholder(domain, RuntimeError("timeout"))
    assert page["path"] == "/__domains__/挚友关系管理/_overview"
    assert page["page_type"] == "domain_overview"


class TestIncrementalDomainFiltering:
    @pytest.mark.asyncio
    async def test_incremental_filters_to_affected_domains_only(self):
        """When is_incremental=True, only affected domains should be processed."""
        state = {
            "domain_tree": [
                {"name": "ChangedDomain", "modules": ["Mod1"], "children": []},
                {"name": "UnchangedDomain", "modules": ["Mod2"], "children": []},
            ],
            "module_summaries": {"Mod1": "s1", "Mod2": "s2"},
            "errors": [],
            "is_incremental": True,
            "affected_domains": ["ChangedDomain"],
        }
        config = {"configurable": {"llm": MagicMock(), "graph_store": MagicMock()}}

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            instance = AsyncMock()
            instance.generate_with_iterations = AsyncMock(
                return_value=[{"type": "domain_overview", "title": "ChangedDomain", "content": "ok"}]
            )
            instance.iteration_history = []
            MockAgent.return_value = instance

            result = await compose_domain_agents_node(state, config)

        assert len(result["pages"]) == 1
        assert result["pages"][0]["title"] == "ChangedDomain"
        assert MockAgent.call_count == 1

    @pytest.mark.asyncio
    async def test_non_incremental_processes_all_domains(self):
        """When is_incremental=False, all domains should be processed."""
        state = {
            "domain_tree": [
                {"name": "DomainA", "modules": ["Mod1"], "children": []},
                {"name": "DomainB", "modules": ["Mod2"], "children": []},
            ],
            "module_summaries": {},
            "errors": [],
            "is_incremental": False,
            "affected_domains": ["DomainA"],
        }
        config = {"configurable": {"llm": MagicMock(), "graph_store": MagicMock()}}

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            instance = AsyncMock()
            instance.generate_with_iterations = AsyncMock(
                return_value=[{"type": "domain_overview", "title": "D", "content": "c"}]
            )
            instance.iteration_history = []
            MockAgent.return_value = instance

            result = await compose_domain_agents_node(state, config)

        assert len(result["pages"]) == 2

    @pytest.mark.asyncio
    async def test_incremental_with_parent_match(self):
        """Affected domain should include child domains under an affected parent."""
        state = {
            "domain_tree": [
                {
                    "name": "ParentDomain",
                    "modules": [],
                    "children": [
                        {"name": "ChildA", "modules": ["Mod1"], "children": []},
                        {"name": "ChildB", "modules": ["Mod2"], "children": []},
                    ],
                },
            ],
            "module_summaries": {},
            "errors": [],
            "is_incremental": True,
            "affected_domains": ["ParentDomain"],
        }
        config = {"configurable": {"llm": MagicMock(), "graph_store": MagicMock()}}

        with patch("wiki.nodes.domain_compose.DomainDocAgent") as MockAgent:
            instance = AsyncMock()
            instance.generate_with_iterations = AsyncMock(
                return_value=[{"type": "domain_overview", "title": "Child", "content": "c"}]
            )
            instance.iteration_history = []
            MockAgent.return_value = instance

            result = await compose_domain_agents_node(state, config)

        # Both children should be processed since ParentDomain is affected
        assert len(result["pages"]) == 2
