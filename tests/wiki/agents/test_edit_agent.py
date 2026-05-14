import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete_with_tools = AsyncMock(return_value={"tool_calls": None})
    llm.generate = AsyncMock(return_value="# Edited Page\n\nNew content here")
    return llm


@pytest.mark.asyncio
async def test_edit_agent_creation(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent
    agent = WikiEditAgent(mock_llm, graph=MagicMock())
    assert agent is not None


@pytest.mark.asyncio
async def test_run_edit_stream_emits_done(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent, EditEventQueue
    agent = WikiEditAgent(mock_llm, graph=MagicMock())
    queue = EditEventQueue()

    task = asyncio.create_task(
        agent.run_edit_stream(
            prompt="Add more detail",
            current_content="# Page\n\n## Section 1\nOld content",
            conversation_history=[],
            event_queue=queue,
        )
    )

    events = []
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=5.0)
        events.append(event)
        if event.type in ("done", "error"):
            break

    result = await task
    assert result == "# Edited Page\n\nNew content here"

    event_types = [e.type for e in events]
    assert "done" in event_types
    done_event = next(e for e in events if e.type == "done")
    assert done_event.result is not None


@pytest.mark.asyncio
async def test_run_edit_stream_error(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent, EditEventQueue
    mock_llm.generate.side_effect = RuntimeError("LLM failed")
    agent = WikiEditAgent(mock_llm, graph=MagicMock())
    queue = EditEventQueue()

    with pytest.raises(RuntimeError):
        await agent.run_edit_stream(
            prompt="test",
            current_content="# Page",
            conversation_history=[],
            event_queue=queue,
        )

    events = []
    while not queue._queue.empty():
        events.append(await queue.get())
    error_events = [e for e in events if e.type == "error"]
    assert len(error_events) >= 1
