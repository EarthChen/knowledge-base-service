import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.agents.agent_tool import agent_tool
from wiki.agents.base_agent import ToolDef
from wiki.agents.runner import AgentLoopResult, LoopConfig


@pytest.fixture
def mock_sub_agent_factory():
    def factory():
        agent = MagicMock()
        agent._tool_registry = MagicMock()
        agent._tool_registry.has_tools.return_value = True
        agent._tool_registry.get_tools_for_round.return_value = []
        agent.create_memory.return_value = {}
        agent.incorporate = MagicMock()
        agent.memory_to_prompt = MagicMock(return_value="Research findings: X depends on Y")
        agent._llm = MagicMock()
        agent._llm.complete_with_tools = AsyncMock(
            return_value={"content": "Sub-agent result", "tool_calls": None}
        )
        return agent

    return factory


def test_agent_tool_returns_tooldef(mock_sub_agent_factory):
    """agent_tool() returns a valid ToolDef."""
    tool = agent_tool(
        agent_factory=mock_sub_agent_factory,
        name="research_specialist",
        description="Deep research on a topic",
    )
    assert isinstance(tool, ToolDef)
    assert tool.name == "research_specialist"
    assert tool.tier == 2


@pytest.mark.asyncio
async def test_agent_tool_executes_sub_agent(mock_sub_agent_factory):
    """agent_tool handler runs the sub-agent and returns structured result."""
    with patch("wiki.agents.agent_tool.run_agent_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = AgentLoopResult(
            memory={},
            final_output="Sub-agent result",
            total_rounds=1,
            total_tool_calls=0,
            exit_reason="text_output",
        )
        tool = agent_tool(
            agent_factory=mock_sub_agent_factory,
            name="research_specialist",
            description="Deep research",
        )
        result = await tool.handler({"query": "How does auth work?"})

        mock_loop.assert_awaited_once()
        call_kwargs = mock_loop.await_args.kwargs
        assert call_kwargs["user_prompt"] == "How does auth work?"
        assert result["output"] == "Sub-agent result"
        assert result["tool_calls_used"] == 0
        assert result["rounds_used"] == 1


@pytest.mark.asyncio
async def test_agent_tool_custom_config(mock_sub_agent_factory):
    """Custom LoopConfig is passed through to run_agent_loop."""
    custom_config = LoopConfig(max_rounds=2, max_tool_calls=5)
    with patch("wiki.agents.agent_tool.run_agent_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = AgentLoopResult(
            memory={},
            final_output="Done",
            total_rounds=2,
            total_tool_calls=3,
        )
        tool = agent_tool(
            agent_factory=mock_sub_agent_factory,
            name="research_specialist",
            description="Deep research",
            config=custom_config,
        )
        result = await tool.handler({"query": "test"})

        assert mock_loop.await_args.kwargs["config"] is custom_config
        assert result["rounds_used"] == 2
        assert result["tool_calls_used"] == 3
