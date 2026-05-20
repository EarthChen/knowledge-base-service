from unittest.mock import MagicMock

from wiki.page_agent import WikiPageAgent


def _get_tool_schemas():
    agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
    return agent._tool_registry.get_all_tool_schemas()


def test_delegate_submodule_tool_exists_in_definitions():
    schemas = _get_tool_schemas()
    tool_names = [t["function"]["name"] for t in schemas]
    assert "delegate_submodule" in tool_names


def test_delegate_submodule_tool_has_entity_names_param():
    schemas = _get_tool_schemas()
    delegate_tool = next(
        t for t in schemas if t["function"]["name"] == "delegate_submodule"
    )
    params = delegate_tool["function"]["parameters"]["properties"]
    assert "entity_names" in params
    assert params["entity_names"]["type"] == "array"


def test_delegate_submodule_tool_has_focus_param():
    schemas = _get_tool_schemas()
    delegate_tool = next(
        t for t in schemas if t["function"]["name"] == "delegate_submodule"
    )
    params = delegate_tool["function"]["parameters"]["properties"]
    assert "focus" in params
    assert params["focus"]["type"] == "string"
