import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.agents.runner import AgentLoopResult, LoopConfig, LoopHooks, run_agent_loop


@pytest.fixture
def mock_agent():
    """Create a minimal mock GenericAgent."""
    agent = MagicMock()
    agent._tool_registry = MagicMock()
    agent._tool_registry.has_tools.return_value = True
    agent._tool_registry.get_tools_for_round.return_value = [
        {"type": "function", "function": {"name": "test_tool", "description": "test", "parameters": {}}}
    ]
    agent._tool_registry.dispatch = AsyncMock(return_value=({"data": "result"}, '{"data":"result"}'))
    agent.incorporate = MagicMock()
    agent._llm = MagicMock()
    agent._llm.complete_with_tools = AsyncMock(return_value={"content": "Final answer", "tool_calls": None})
    return agent


@pytest.mark.asyncio
async def test_run_agent_loop_basic_text_output(mock_agent):
    """Agent returns text on first round -> loop exits with text output."""
    result = await run_agent_loop(
        mock_agent,
        system_prompt="You are helpful.",
        user_prompt="Do something.",
        memory={},
        config=LoopConfig(nudge_message=""),
    )
    assert isinstance(result, AgentLoopResult)
    assert result.final_output == "Final answer"
    assert result.exit_reason == "text_output"
    assert result.total_rounds == 1
    assert result.total_tool_calls == 0


@pytest.mark.asyncio
async def test_run_agent_loop_tool_execution(mock_agent):
    """Agent calls tools then returns text -> loop processes tools and exits."""
    mock_agent._llm.complete_with_tools = AsyncMock(side_effect=[
        {"tool_calls": [{"id": "tc1", "function": {"name": "test_tool", "arguments": '{"q":"hello"}'}}]},
        {"content": "Done!", "tool_calls": None},
    ])
    result = await run_agent_loop(mock_agent, "sys", "user", memory={})
    assert result.total_tool_calls == 1
    assert result.final_output == "Done!"
    assert result.exit_reason == "text_output"
    mock_agent.incorporate.assert_called_once()


@pytest.mark.asyncio
async def test_repeated_call_detection(mock_agent):
    """Agent calling same tool with same args consecutively triggers detection."""
    same_call = {"id": "tc1", "function": {"name": "search", "arguments": '{"q":"auth"}'}}
    mock_agent._llm.complete_with_tools = AsyncMock(side_effect=[
        {"tool_calls": [same_call]},
        {"tool_calls": [same_call]},
        {"content": "result", "tool_calls": None},
    ])

    result = await run_agent_loop(
        mock_agent, "sys", "user", memory={},
        config=LoopConfig(max_consecutive_repeats=2, detect_repeated_calls=True),
    )
    assert result.repeated_calls_detected >= 1


@pytest.mark.asyncio
async def test_repeated_detection_disabled(mock_agent):
    """When detection is off, repeated calls execute normally."""
    same_call = {"id": "tc1", "function": {"name": "search", "arguments": '{"q":"auth"}'}}
    mock_agent._llm.complete_with_tools = AsyncMock(side_effect=[
        {"tool_calls": [same_call]},
        {"tool_calls": [same_call]},
        {"content": "result", "tool_calls": None},
    ])

    result = await run_agent_loop(
        mock_agent, "sys", "user", memory={},
        config=LoopConfig(detect_repeated_calls=False),
    )
    assert result.repeated_calls_detected == 0
    assert mock_agent._tool_registry.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_on_no_tool_calls_hook_nudge(mock_agent):
    """Hook returns nudge string -> loop continues with nudge message."""
    call_count = [0]

    async def nudge_hook(round_num, text, total_calls):
        call_count[0] += 1
        if total_calls == 0 and round_num == 0:
            return "Use tools first!"
        return None

    mock_agent._llm.complete_with_tools = AsyncMock(side_effect=[
        {"content": "I'll skip tools", "tool_calls": None},
        {"content": "OK fine here's the answer", "tool_calls": None},
    ])

    result = await run_agent_loop(
        mock_agent, "sys", "user", memory={},
        config=LoopConfig(hooks=LoopHooks(on_no_tool_calls=nudge_hook)),
    )
    assert result.final_output == "OK fine here's the answer"
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_tool_dispatch_exception_continues_loop(mock_agent):
    """Unexpected tool exception is caught; loop continues instead of aborting."""
    mock_agent._tool_registry.dispatch = AsyncMock(side_effect=RuntimeError("db connection lost"))
    mock_agent._llm.complete_with_tools = AsyncMock(side_effect=[
        {"tool_calls": [{"id": "tc1", "function": {"name": "test_tool", "arguments": "{}"}}]},
        {"content": "Recovered after tool failure", "tool_calls": None},
    ])

    result = await run_agent_loop(mock_agent, "sys", "user", memory={})

    assert result.final_output == "Recovered after tool failure"
    assert result.exit_reason == "text_output"
    assert result.total_tool_calls == 1
    mock_agent.incorporate.assert_called_once()
    tool_result = mock_agent.incorporate.call_args[0][1]
    assert "error" in tool_result
    assert "db connection lost" in tool_result["error"]


@pytest.mark.asyncio
async def test_on_loop_complete_hook_fallback(mock_agent):
    """Hook generates fallback output when loop exits without text."""
    async def fallback_hook(memory):
        return "Fallback generated content"

    mock_agent._tool_registry.has_tools.return_value = False

    result = await run_agent_loop(
        mock_agent, "sys", "user", memory={},
        config=LoopConfig(hooks=LoopHooks(on_loop_complete=fallback_hook)),
    )
    assert result.final_output == "Fallback generated content"
    assert result.exit_reason == "hook_fallback"
