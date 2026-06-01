from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_delegate_submodule_uses_execute_delegation():
    """delegate_submodule should internally call execute_delegation."""
    from wiki.page_agent import WikiPageAgent

    agent = WikiPageAgent.__new__(WikiPageAgent)
    agent._deps = MagicMock()
    agent._deps.delegation_depth = 0
    agent._deps.delegation_count = 0
    agent._delegation_depth = 0
    agent._delegation_count = 0
    agent._llm = MagicMock()
    agent.max_rounds = 10
    agent.max_tool_calls = 50
    agent._existing_pages = {}
    agent._current_memory = MagicMock()
    agent._current_memory.slice = MagicMock(return_value=MagicMock())
    agent._current_memory.merge = MagicMock()

    with patch("wiki.agents.delegation.execute_delegation") as mock_deleg:
        mock_deleg.return_value = MagicMock(
            output="delegated result",
            tool_calls_made=5,
            child_memory=None,
            metadata={},
        )
        result = await agent.delegate_submodule(entity_names=["ModuleA"])

        mock_deleg.assert_called_once()
        config_arg = mock_deleg.call_args[0][0]
        assert config_arg is not None
        assert result.get("delegated") is True
        assert result.get("content") == "delegated result"

