import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.agents.events import ToolCallEvent
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


def test_wiki_edit_agent_registers_tools_with_graph(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent

    agent = WikiEditAgent(mock_llm, graph=MagicMock())
    assert agent._tool_registry.has_tools()
    names = {
        s["function"]["name"] for s in agent._tool_registry.get_all_tool_schemas()
    }
    assert names == {
        "get_call_chain",
        "query_module_detail",
        "read_source_file",
        "search_entities",
        "search_wiki_pages",
    }


def test_wiki_edit_agent_no_tools_without_graph(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent

    agent = WikiEditAgent(mock_llm)
    assert not agent._tool_registry.has_tools()


@pytest.mark.asyncio
async def test_tool_search_entities_graph_unavailable_returns_error(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent

    agent = WikiEditAgent(mock_llm, graph=MagicMock())
    res = await agent._tool_registry.dispatch("search_entities", {"query": "x"})
    assert "error" in res


@pytest.mark.asyncio
async def test_tool_search_entities_dispatch(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent

    graph = MagicMock()
    graph.execute_query = AsyncMock(
        return_value=MagicMock(data=[
            {
                "uid": "u1",
                "name": "svc",
                "label": "Module",
                "description": "svc desc",
            }
        ]),
    )
    agent = WikiEditAgent(mock_llm, graph=graph)
    res = await agent._tool_registry.dispatch(
        "search_entities", {"query": "svc", "limit": 5}
    )
    assert res.get("error") is None
    assert res["total"] == 1
    assert res["results"][0]["uid"] == "u1"


@pytest.mark.asyncio
async def test_tool_query_module_detail_dispatch(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent

    graph = MagicMock()
    graph.execute_query = AsyncMock(side_effect=[
        MagicMock(data=[{"func_name": "run", "signature": "() -> None", "file_path": "a.py"}]),
        MagicMock(data=[{"name": "DepMod"}]),
        MagicMock(data=[{"name": "CallerMod"}]),
    ])
    agent = WikiEditAgent(mock_llm, graph=graph)
    res = await agent._tool_registry.dispatch(
        "query_module_detail", {"module_name": "MyMod"}
    )
    assert res.get("error") is None
    assert res["module_name"] == "MyMod"
    assert res["methods"][0]["name"] == "run"
    assert res["outgoing_dependencies"] == ["DepMod"]
    assert res["incoming_dependencies"] == ["CallerMod"]
    assert graph.execute_query.await_count == 3


@pytest.mark.asyncio
async def test_tool_search_wiki_pages_dispatch(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent

    graph = MagicMock()
    graph.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"title": "T", "path": "/p", "snippet": "body"}]),
    )
    agent = WikiEditAgent(mock_llm, graph=graph)
    res = await agent._tool_registry.dispatch(
        "search_wiki_pages", {"query": "body", "limit": 5}
    )
    assert res.get("error") is None
    assert res["pages"][0]["path"] == "/p"


@pytest.mark.asyncio
async def test_run_edit_stream_calls_complete_with_tools_when_graph_present(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent, EditEventQueue

    graph = MagicMock()
    graph.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"uid": "u", "name": "x", "label": "M", "description": ""}]),
    )
    mock_llm.complete_with_tools = AsyncMock(side_effect=[
        {
            "role": "assistant",
            "tool_calls": [{
                "id": "tc1",
                "function": {
                    "name": "search_entities",
                    "arguments": json.dumps({"query": "x"}),
                },
            }],
        },
        {"tool_calls": None},
    ])
    agent = WikiEditAgent(mock_llm, graph=graph)
    queue = EditEventQueue()

    async def drain_until_done():
        collected: list = []
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=5.0)
            collected.append(event)
            if event.type in ("done", "error"):
                break
        return collected

    edit_task = asyncio.create_task(
        agent.run_edit_stream(
            prompt="Improve",
            current_content="# Page",
            conversation_history=[],
            event_queue=queue,
        )
    )
    events_task = asyncio.create_task(drain_until_done())

    _, events = await asyncio.gather(edit_task, events_task)

    tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
    assert mock_llm.complete_with_tools.await_count >= 2
    assert len(tool_events) == 1
    assert tool_events[0].tool == "search_entities"


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


def test_edit_working_memory_budget_enforcement():
    from wiki.agents.edit_agent import EditWorkingMemory

    m = EditWorkingMemory()
    m.MAX_TOTAL_CHARS = 500
    m.focus_sections = ["x" * 100]
    m.outline = ["y" * 100]
    m.context_sections = ["c0" * 50, "c1" * 50]
    m.incorporate_tool_result("t1", {"k": "z" * 400})
    assert m.total_chars() <= m.MAX_TOTAL_CHARS


def test_edit_working_memory_eviction_priority():
    from wiki.agents.edit_agent import EditWorkingMemory

    m = EditWorkingMemory()
    m.MAX_TOTAL_CHARS = 50
    m.focus_sections = ["F" * 10]
    m.outline = ["O" * 10]
    m.context_sections = ["C" * 25, "D" * 25]
    m.incorporate_tool_result("tool_a", {"v": "x"})
    assert m.context_sections == []
    assert len(m.tool_results) == 1


@pytest.mark.asyncio
async def test_run_edit_stream_uses_sections(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent, EditEventQueue

    filler = "word " * 2000
    current_content = (
        f"## Intro\n{filler}\n\n## Target Section\ntiny\n\n## Outro\n{filler}\n"
    )
    assert len(current_content) > 5000

    captured: dict[str, str] = {}

    async def generate_side_effect(*args, **kwargs):
        captured["system"] = kwargs.get("system", "")
        return "# Edited\n\nok"

    mock_llm.generate = AsyncMock(side_effect=generate_side_effect)

    agent = WikiEditAgent(mock_llm)
    queue = EditEventQueue()
    await agent.run_edit_stream(
        prompt="Update Target Section only",
        current_content=current_content,
        conversation_history=[],
        event_queue=queue,
    )

    sys = captured["system"]
    assert "## Current page (focused sections)" in sys
    assert len(sys) < len(current_content)
    assert "Target Section" in sys


@pytest.mark.asyncio
async def test_run_edit_stream_small_page_full_content_in_system(mock_llm):
    from wiki.agents.edit_agent import WikiEditAgent, EditEventQueue

    captured: dict[str, str] = {}

    async def generate_side_effect(*args, **kwargs):
        captured["system"] = kwargs.get("system", "")
        return "# ok"

    mock_llm.generate = AsyncMock(side_effect=generate_side_effect)

    short = "## A\n\nhello"
    agent = WikiEditAgent(mock_llm)
    queue = EditEventQueue()
    await agent.run_edit_stream(
        prompt="edit",
        current_content=short,
        conversation_history=[],
        event_queue=queue,
    )
    assert short in captured["system"]
    assert "focused sections" not in captured["system"]


class TestReadSourceFileTool:
    @pytest.mark.asyncio
    async def test_read_source_returns_content(self, mock_llm):
        from wiki.agents.edit_agent import WikiEditAgent

        graph = MagicMock()
        graph.execute_query = AsyncMock(
            return_value=MagicMock(
                data=[
                    {
                        "path": "src/foo.py",
                        "content": "print('hi')",
                    }
                ]
            ),
        )
        agent = WikiEditAgent(mock_llm, graph=graph)
        res = await agent._tool_registry.dispatch(
            "read_source_file", {"path": "src/foo.py"}
        )
        assert res.get("error") is None
        assert res["found"] is True
        assert res["path"] == "src/foo.py"
        assert res["content"] == "print('hi')"

    @pytest.mark.asyncio
    async def test_read_source_missing_path(self, mock_llm):
        from wiki.agents.edit_agent import WikiEditAgent

        agent = WikiEditAgent(mock_llm, graph=MagicMock())
        res = await agent._tool_registry.dispatch("read_source_file", {"path": ""})
        assert res.get("error") == "missing path"


class TestGetCallChainTool:
    @pytest.mark.asyncio
    async def test_get_call_chain_returns_callees(self, mock_llm):
        from wiki.agents.edit_agent import WikiEditAgent

        graph = MagicMock()
        graph.execute_query = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"name": "helper", "file_path": "h.py"},
                    {"name": "utils", "file_path": "u.py"},
                ]
            ),
        )
        agent = WikiEditAgent(mock_llm, graph=graph)
        res = await agent._tool_registry.dispatch(
            "get_call_chain", {"func_name": "main"}
        )
        assert res.get("error") is None
        assert res["func_name"] == "main"
        assert res["total"] == 2
        assert res["callees"][0]["name"] == "helper"
        assert res["callees"][0]["file_path"] == "h.py"

    @pytest.mark.asyncio
    async def test_get_call_chain_missing_name(self, mock_llm):
        from wiki.agents.edit_agent import WikiEditAgent

        agent = WikiEditAgent(mock_llm, graph=MagicMock())
        res = await agent._tool_registry.dispatch(
            "get_call_chain", {"func_name": ""}
        )
        assert res.get("error") == "missing func_name"


class TestSectionedEditReassembly:
    @pytest.mark.asyncio
    async def test_large_page_uses_reassemble(self, mock_llm):
        from wiki.agents.edit_agent import WikiEditAgent, EditEventQueue
        from wiki.agents.section_utils import split_page_into_sections

        filler = "keep " * 2000
        current_content = (
            f"## Intro\n{filler}\n\n## Target Section\nold target\n\n## Outro\n{filler}\n"
        )
        assert len(current_content) > 5000

        async def generate_side_effect(*args, **kwargs):
            return "## Target Section\nedited target"

        mock_llm.generate = AsyncMock(side_effect=generate_side_effect)

        agent = WikiEditAgent(mock_llm)
        queue = EditEventQueue()
        result = await agent.run_edit_stream(
            prompt="Update Target Section wording",
            current_content=current_content,
            conversation_history=[],
            event_queue=queue,
        )

        assert "## Intro" in result
        assert filler.strip()[:20] in result
        assert "old target" not in result
        assert "edited target" in result
        secs = split_page_into_sections(result)
        by_heading = {
            s.heading.strip("# ").strip(): s.body.strip()
            for s in secs
            if s.heading
        }
        assert "edited target" in by_heading.get("Target Section", "")
