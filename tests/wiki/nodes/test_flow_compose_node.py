from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from wiki.nodes.flow_compose import compose_flow_agents_node, merge_flow_pages_node


class TestComposeFlowAgentsNode:
    @pytest.mark.asyncio
    async def test_skips_when_no_llm(self):
        state = {"domain_tree": [{"name": "d1", "modules": ["m1"]}]}
        result = await compose_flow_agents_node(state, config={"configurable": {}})
        assert result["flow_pages"] == []

    @pytest.mark.asyncio
    async def test_skips_domain_without_entry_points(self):
        from wiki.flow_baseline import FlowBaseline

        mock_llm = AsyncMock()
        mock_graph = AsyncMock()
        state = {"domain_tree": [{"name": "utils", "modules": ["StringUtils"]}]}

        with patch("wiki.nodes.flow_compose.extract_flow_baseline") as mock_extract:
            mock_extract.return_value = FlowBaseline("utils", [], [], 1, [])
            result = await compose_flow_agents_node(
                state, config={"configurable": {"llm": mock_llm, "graph_store": mock_graph}}
            )
        assert result["flow_pages"] == []

    @pytest.mark.asyncio
    async def test_uses_flow_pages_state_key(self):
        """Verify output uses 'flow_pages' not 'pages' to avoid overwrite."""
        mock_llm = AsyncMock()
        mock_graph = AsyncMock()
        state = {"domain_tree": [{"name": "d1", "modules": ["m1"]}]}

        from wiki.flow_baseline import EntryPointInfo, FlowBaseline

        with (
            patch("wiki.nodes.flow_compose.extract_flow_baseline") as mock_extract,
            patch("wiki.nodes.flow_compose._run_flow_agent") as mock_agent,
        ):
            mock_extract.return_value = FlowBaseline(
                "d1", [EntryPointInfo("create", "Ctrl", "http", "f.py")], [], 1, []
            )
            mock_agent.return_value = [{"path": "d1/flows.md", "page_type": "business_flow", "content": "# Flow"}]
            result = await compose_flow_agents_node(
                state, config={"configurable": {"llm": mock_llm, "graph_store": mock_graph}}
            )
        assert "flow_pages" in result
        assert "pages" not in result
        assert len(result["flow_pages"]) == 1

    @pytest.mark.asyncio
    async def test_disabled_by_config(self):
        mock_llm = AsyncMock()
        state = {"domain_tree": [{"name": "d1", "modules": ["m1"]}]}
        with patch("wiki.nodes.flow_compose._is_flow_enabled", return_value=False):
            result = await compose_flow_agents_node(
                state, config={"configurable": {"llm": mock_llm}}
            )
        assert result["flow_pages"] == []

    @pytest.mark.asyncio
    async def test_incremental_only_processes_affected_domains(self):
        """Incremental run with 2/5 affected domains should only generate those flow pages."""
        from wiki.flow_baseline import EntryPointInfo, FlowBaseline

        mock_llm = AsyncMock()
        mock_graph = AsyncMock()
        domain_names = [f"domain-{i}" for i in range(5)]
        domain_tree = [{"name": name, "modules": [f"mod-{name}"]} for name in domain_names]
        affected = {"domain-1", "domain-3"}
        state = {
            "domain_tree": domain_tree,
            "is_incremental": True,
            "affected_domains": sorted(affected),
        }

        processed_domains: list[str] = []

        async def mock_agent(domain_name, *args, **kwargs):
            processed_domains.append(domain_name)
            return [{"path": f"{domain_name}/business-flows.md", "page_type": "business_flow", "content": "# Flow"}]

        baseline = FlowBaseline(
            "x", [EntryPointInfo("create", "Ctrl", "http", "f.py")], [], 1, [],
        )

        with (
            patch("wiki.nodes.flow_compose._is_flow_enabled", return_value=True),
            patch("wiki.nodes.flow_compose.extract_flow_baseline", return_value=baseline),
            patch("wiki.nodes.flow_compose._run_flow_agent", side_effect=mock_agent),
            patch("wiki.nodes.flow_compose._persist_flow_structure", new_callable=AsyncMock),
        ):
            result = await compose_flow_agents_node(
                state, config={"configurable": {"llm": mock_llm, "graph_store": mock_graph}}
            )

        assert set(processed_domains) == affected
        assert len(result["flow_pages"]) == 2


class TestMergeFlowPagesNode:
    @pytest.mark.asyncio
    async def test_noop_when_empty(self):
        state = {"pages": [{"path": "a.md"}], "flow_pages": []}
        assert await merge_flow_pages_node(state) == {}

    @pytest.mark.asyncio
    async def test_merges_into_pages(self):
        flow_page = {"path": "d1/business-flows.md", "page_type": "business_flow", "content": "# Flow"}
        state = {"pages": [{"path": "a.md"}], "flow_pages": [flow_page]}
        result = await merge_flow_pages_node(state)
        assert result == {"pages": [flow_page]}
