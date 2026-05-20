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

    def test_tool_tiers_are_assigned(self):
        from wiki.page_agent import WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        tier_1_expected = {"query_module_detail", "read_code", "query_call_chain", "query_callers", "query_callees"}
        tier_2_expected = {"query_implementations", "query_domain_dependencies", "read_file", "search_entities"}
        tier_3_expected = {"grep_code", "list_files", "semantic_search", "read_wiki_page", "delegate_submodule"}

        for tool_def in agent._tool_registry._tools.values():
            if tool_def.name in tier_1_expected:
                assert tool_def.tier == 1, f"{tool_def.name} should be tier 1"
            elif tool_def.name in tier_2_expected:
                assert tool_def.tier == 2, f"{tool_def.name} should be tier 2"
            elif tool_def.name in tier_3_expected:
                assert tool_def.tier == 3, f"{tool_def.name} should be tier 3"

    def test_all_tools_have_explicit_tier(self):
        from wiki.page_agent import WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        for tool_def in agent._tool_registry._tools.values():
            assert tool_def.tier in (1, 2, 3), f"{tool_def.name} has invalid tier {tool_def.tier}"

    def test_registered_tools_have_callable_handlers(self):
        """Each registered tool should exist in the registry with a callable handler."""
        from wiki.page_agent import WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=None)
        tool = agent._tool_registry._tools.get("query_module_detail")
        assert tool is not None
        assert callable(tool.handler)
