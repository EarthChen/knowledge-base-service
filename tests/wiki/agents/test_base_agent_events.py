import pytest
from unittest.mock import AsyncMock
from typing import Any

from wiki.agents.base_agent import GenericAgent, ToolDef
from wiki.agents.events import (
    AgentEvent, ThinkingEvent, ToolCallEvent, ToolResultEvent,
)


class StubAgent(GenericAgent):
    def incorporate(self, tool_name: str, result: dict[str, Any], memory: Any) -> None:
        if not hasattr(memory, "results"):
            memory.results = []
        memory.results.append((tool_name, result))

    def memory_to_prompt(self, memory: Any) -> str:
        return ""


class SimpleMemory:
    results: list = []


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete_with_tools = AsyncMock()
    llm.generate = AsyncMock(return_value="")
    return llm


@pytest.mark.asyncio
async def test_event_callback_receives_thinking_event(mock_llm):
    mock_llm.complete_with_tools.return_value = {"tool_calls": None}
    agent = StubAgent(mock_llm, max_rounds=2)
    events: list[AgentEvent] = []

    async def collector(event: AgentEvent) -> None:
        events.append(event)

    async def dummy_handler(args):
        return {"ok": True}

    agent._tool_registry.register(
        ToolDef(name="dummy", description="d", parameters={}, handler=dummy_handler)
    )
    await agent.run_tool_loop("sys", "usr", SimpleMemory(), event_callback=collector)

    thinking_events = [e for e in events if isinstance(e, ThinkingEvent)]
    assert len(thinking_events) >= 1
    assert thinking_events[0].round_num == 1
    assert thinking_events[0].text
    assert "round 1" in thinking_events[0].text.lower()


@pytest.mark.asyncio
async def test_event_callback_receives_tool_events(mock_llm):
    mock_llm.complete_with_tools.side_effect = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "tc1", "function": {"name": "dummy", "arguments": '{"q": "test"}'}}
            ],
        },
        {"tool_calls": None},
    ]
    agent = StubAgent(mock_llm, max_rounds=3)
    events: list[AgentEvent] = []

    async def collector(event: AgentEvent) -> None:
        events.append(event)

    async def dummy_handler(args):
        return {"data": "result"}

    agent._tool_registry.register(
        ToolDef(name="dummy", description="d", parameters={}, handler=dummy_handler)
    )
    await agent.run_tool_loop("sys", "usr", SimpleMemory(), event_callback=collector)

    tool_call_events = [e for e in events if isinstance(e, ToolCallEvent)]
    tool_result_events = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].tool == "dummy"
    assert tool_call_events[0].args == {"q": "test"}
    assert len(tool_result_events) == 1
    assert tool_result_events[0].tool == "dummy"


@pytest.mark.asyncio
async def test_no_callback_backward_compat(mock_llm):
    mock_llm.complete_with_tools.return_value = {"tool_calls": None}
    agent = StubAgent(mock_llm, max_rounds=1)
    agent._tool_registry.register(
        ToolDef(name="x", description="x", parameters={}, handler=AsyncMock(return_value={}))
    )
    result = await agent.run_tool_loop("sys", "usr", SimpleMemory())
    assert result is not None
