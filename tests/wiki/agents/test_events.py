from wiki.agents.events import (
    AgentEvent, ThinkingEvent, ToolCallEvent, ToolResultEvent,
    ContentEvent, DoneEvent, ErrorEvent, EventCallback,
)


def test_thinking_event_defaults():
    e = ThinkingEvent()
    assert e.type == "thinking"
    assert e.round_num == 0
    assert e.text == ""


def test_thinking_event_with_values():
    e = ThinkingEvent(round_num=3, text="Analyzing...")
    assert e.type == "thinking"
    assert e.round_num == 3


def test_tool_call_event():
    e = ToolCallEvent(tool="search_entities", args={"query": "foo"})
    assert e.type == "tool_call"
    assert e.tool == "search_entities"
    assert e.args == {"query": "foo"}


def test_tool_result_event():
    e = ToolResultEvent(tool="search_entities", summary="Found 3 entities")
    assert e.type == "tool_result"
    assert e.summary == "Found 3 entities"


def test_content_event():
    e = ContentEvent(text="## Hello")
    assert e.type == "content"


def test_done_event():
    e = DoneEvent(result={"full_content": "# Page"})
    assert e.type == "done"
    assert e.result == {"full_content": "# Page"}


def test_error_event():
    e = ErrorEvent(message="timeout")
    assert e.type == "error"
    assert e.message == "timeout"


def test_all_are_subclasses():
    for cls in (ThinkingEvent, ToolCallEvent, ToolResultEvent, ContentEvent, DoneEvent, ErrorEvent):
        assert issubclass(cls, AgentEvent)


def test_event_callback_type_exists():
    assert EventCallback is not None
