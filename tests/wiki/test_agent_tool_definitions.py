"""Tests for P0: tool definitions correctness."""
from __future__ import annotations

from wiki.page_agent import AGENT_TOOLS


class TestToolDefinitions:
    def test_read_source_snippet_not_in_tools(self):
        """read_source_snippet should no longer be exposed to LLM."""
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "read_source_snippet" not in names

    def test_all_tools_have_description(self):
        for tool in AGENT_TOOLS:
            desc = tool["function"]["description"]
            assert len(desc) > 20, f"{tool['function']['name']} has too short description"

    def test_all_descriptions_contain_use_guidance(self):
        """Each tool description should contain 'Use when' or 'Use to' or 'Use for'."""
        for tool in AGENT_TOOLS:
            desc = tool["function"]["description"]
            name = tool["function"]["name"]
            assert "Use " in desc, f"{name} description lacks usage guidance"

    def test_expected_tool_count(self):
        """Should have exactly 13 tools (list_files, grep_code, query_domain_dependencies added; read_source_snippet removed)."""
        assert len(AGENT_TOOLS) == 13

    def test_tool_names_are_unique(self):
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert len(names) == len(set(names))

    def test_read_code_description_mentions_indexed(self):
        """read_code description should clarify it's for indexed entities."""
        for tool in AGENT_TOOLS:
            if tool["function"]["name"] == "read_code":
                assert "indexed" in tool["function"]["description"].lower()

    def test_read_file_description_mentions_config(self):
        """read_file description should clarify it's for non-indexed files."""
        for tool in AGENT_TOOLS:
            if tool["function"]["name"] == "read_file":
                desc = tool["function"]["description"].lower()
                assert "config" in desc or "non-indexed" in desc
