import pytest
from wiki.page_agent import AGENT_TOOLS


def test_delegate_submodule_tool_exists_in_definitions():
    tool_names = [t["function"]["name"] for t in AGENT_TOOLS]
    assert "delegate_submodule" in tool_names


def test_delegate_submodule_tool_has_entity_names_param():
    delegate_tool = next(
        t for t in AGENT_TOOLS if t["function"]["name"] == "delegate_submodule"
    )
    params = delegate_tool["function"]["parameters"]["properties"]
    assert "entity_names" in params
    assert params["entity_names"]["type"] == "array"


def test_delegate_submodule_tool_has_focus_param():
    delegate_tool = next(
        t for t in AGENT_TOOLS if t["function"]["name"] == "delegate_submodule"
    )
    params = delegate_tool["function"]["parameters"]["properties"]
    assert "focus" in params
    assert params["focus"]["type"] == "string"
