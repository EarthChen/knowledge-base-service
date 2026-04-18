"""Tests for MCP server tool manifest and handler routing."""

from api.mcp_server import MCP_TOOLS_MANIFEST


class TestMCPToolsManifest:
    def test_tool_count(self):
        assert len(MCP_TOOLS_MANIFEST) == 17

    def test_tool_names(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert names == {
            "rag_query",
            "rag_graph",
            "rag_index",
            "rag_business_search",
            "analyze_impact",
            "list_endpoints",
            "check_consistency",
            "review_pr",
            "build_context",
            "search_architecture",
            "code_quality",
            "dashboard_stats",
            "generate_wiki",
            "get_wiki_page",
            "list_wiki_pages",
            "search_wiki",
            "ask_about_code",
        }

    def test_rag_query_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_query")
        schema = tool["inputSchema"]
        assert "query" in schema["properties"]
        assert "query" in schema["required"]

    def test_rag_graph_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_graph")
        schema = tool["inputSchema"]
        assert "query_type" in schema["properties"]
        query_type_enum = schema["properties"]["query_type"]["enum"]
        assert "call_chain" in query_type_enum
        assert "inheritance_tree" in query_type_enum
        assert "raw_cypher" in query_type_enum
        assert "business_flow" in query_type_enum
        assert "flows_for_function" in query_type_enum
        assert "related_concepts" in query_type_enum
        assert "explore_domain" in query_type_enum
        assert "flow_dependencies" in query_type_enum

    def test_rag_index_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_index")
        schema = tool["inputSchema"]
        assert "directory" in schema["properties"]
        assert "directory" in schema["required"]
        assert "mode" in schema["properties"]
        assert schema["properties"]["mode"]["enum"] == ["full", "incremental"]

    def test_analyze_impact_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "analyze_impact")
        schema = tool["inputSchema"]
        assert "changed_functions" in schema["properties"]
        assert schema["properties"]["changed_functions"]["type"] == "array"
        assert "changed_functions" in schema["required"]

    def test_list_endpoints_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "list_endpoints")
        schema = tool["inputSchema"]
        assert schema["properties"] == {}

    def test_check_consistency_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "check_consistency")
        schema = tool["inputSchema"]
        assert "repository" in schema["properties"]
        assert "repository" in schema["required"]

    def test_all_tools_have_description(self):
        for tool in MCP_TOOLS_MANIFEST:
            assert "description" in tool
            assert len(tool["description"]) > 10
