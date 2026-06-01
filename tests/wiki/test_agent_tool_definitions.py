"""Tests for P0: tool definitions correctness."""
from __future__ import annotations

from unittest.mock import MagicMock

from wiki.page_agent import WikiPageAgent


def _get_tool_schemas():
    agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
    return agent._tool_registry.get_all_tool_schemas()


class TestToolDefinitions:
    def test_read_source_snippet_not_in_tools(self):
        """read_source_snippet should no longer be exposed to LLM."""
        schemas = _get_tool_schemas()
        names = [t["function"]["name"] for t in schemas]
        assert "read_source_snippet" not in names

    def test_all_tools_have_description(self):
        for tool in _get_tool_schemas():
            desc = tool["function"]["description"]
            assert len(desc) > 20, f"{tool['function']['name']} has too short description"

    def test_all_descriptions_contain_use_guidance(self):
        """Each tool description should contain 'Use when' or 'Use to' or 'Use for'."""
        for tool in _get_tool_schemas():
            desc = tool["function"]["description"]
            name = tool["function"]["name"]
            assert "Use " in desc, f"{name} description lacks usage guidance"

    def test_expected_tool_count(self):
        """Should have exactly 15 tools (includes delegate_submodule, remember, and graph/wiki query tools)."""
        assert len(_get_tool_schemas()) == 15

    def test_tool_names_are_unique(self):
        schemas = _get_tool_schemas()
        names = [t["function"]["name"] for t in schemas]
        assert len(names) == len(set(names))

    def test_read_code_description_mentions_indexed(self):
        """read_code description should clarify it's for indexed entities."""
        for tool in _get_tool_schemas():
            if tool["function"]["name"] == "read_code":
                assert "indexed" in tool["function"]["description"].lower()

    def test_read_file_description_mentions_config(self):
        """read_file description should clarify it's for non-indexed files."""
        for tool in _get_tool_schemas():
            if tool["function"]["name"] == "read_file":
                desc = tool["function"]["description"].lower()
                assert "config" in desc or "non-indexed" in desc
