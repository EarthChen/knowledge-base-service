"""Tests for compose_leaf_modules_node summaries-only mode."""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.compose import compose_leaf_modules_node


class TestCLMSummariesOnly:
    @pytest.mark.asyncio
    async def test_use_agent_compose_skips_page_generation(self):
        """When USE_AGENT_COMPOSE=true, CLM only produces module_summaries, not pages."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value='{"summary_text": "test summary"}')
        mock_graph = MagicMock()

        state = {
            "modules": {"repo1": [{"uid": "mod1", "name": "UserController", "properties": {"name": "UserController"}}]},
            "module_tree": [{"uid": "mod1", "name": "UserController", "children": []}],
            "canonical_keys": {"mod1": "service/user/UserController"},
            "entity_roles": {},
            "errors": [],
        }
        config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

        with patch.dict(os.environ, {"USE_AGENT_COMPOSE": "true"}):
            result = await compose_leaf_modules_node(state, config)

        assert "module_summaries" in result
        pages = result.get("pages", [])
        module_overview_pages = [p for p in pages if p.get("type") == "module_overview"]
        assert len(module_overview_pages) == 0
