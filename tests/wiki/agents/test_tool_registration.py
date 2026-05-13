from unittest.mock import MagicMock


class TestWikiPageAgentToolRegistration:
    def test_tools_registered_on_init(self):
        from wiki.page_agent import WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        schemas = agent._tool_registry.get_all_tool_schemas()
        names = {s["function"]["name"] for s in schemas}

        expected_tools = {
            "query_module_detail", "query_callers", "query_callees",
            "query_implementations", "query_call_chain",
            "query_domain_dependencies", "read_code", "read_file",
            "search_entities", "read_wiki_page", "semantic_search",
            "list_files", "grep_code", "delegate_submodule",
        }
        assert names == expected_tools

    def test_tool_tiers_match_existing(self):
        from wiki.page_agent import WikiPageAgent, _TOOL_TIERS

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        for tool_def in agent._tool_registry._tools.values():
            expected_tier = _TOOL_TIERS.get(tool_def.name, 1)
            assert tool_def.tier == expected_tier, (
                f"Tool {tool_def.name}: expected tier {expected_tier}, got {tool_def.tier}"
            )

    def test_all_tools_have_explicit_tier(self):
        from wiki.page_agent import AGENT_TOOLS, _TOOL_TIERS

        tool_names = {t["function"]["name"] for t in AGENT_TOOLS}
        missing = tool_names - _TOOL_TIERS.keys()
        assert not missing, f"Tools missing from _TOOL_TIERS: {missing}"

    def test_registered_tools_have_callable_handlers(self):
        """Each registered tool should exist in the registry with a callable handler."""
        from wiki.page_agent import WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=None)
        tool = agent._tool_registry._tools.get("query_module_detail")
        assert tool is not None
        assert callable(tool.handler)
