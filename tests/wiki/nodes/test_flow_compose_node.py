from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from wiki.nodes.flow_compose import compose_flow_agents_node


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
            mock_agent.return_value = [{"path": "d1/flows.md", "page_type": "flow", "content": "# Flow"}]
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
