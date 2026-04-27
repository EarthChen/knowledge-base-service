"""Tests for MCP server tool manifest and handler routing."""

from api.mcp_server import MCP_TOOLS_MANIFEST


class TestMCPToolsManifest:
    def test_tool_count(self):
        assert len(MCP_TOOLS_MANIFEST) == 20

    def test_tool_names(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert names == {
            "rag_query",
            "rag_graph",
            "documents",
            "get_file_content",
            "get_code_snippet",
            "analyze_code",
            "search_architecture",
            "analyze_changes",
            "get_complete_context",
            "get_insights",
            "graph_path",
            "index_freshness",
            "get_wiki_page",
            "list_wiki_pages",
            "search_wiki",
            "wiki_export",
            "wiki_get_tree",
            "wiki_get_related",
            "wiki_get_domain_overview",
            "wiki_get_snapshot",
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
        assert "blast_radius" in query_type_enum

    def test_documents_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "documents")
        assert "uid" in tool["inputSchema"]["properties"]
        assert "repository" in tool["inputSchema"]["properties"]

    def test_get_code_snippet_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "get_code_snippet")
        schema = tool["inputSchema"]
        assert "node_uid" in schema["properties"]
        assert schema["required"] == ["node_uid"]

    def test_analyze_code_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "analyze_code")
        modes = tool["inputSchema"]["properties"]["mode"]["enum"]
        assert modes == ["quality", "consistency"]

    def test_search_architecture_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "search_architecture")
        schema = tool["inputSchema"]
        assert schema["properties"]["mode"]["enum"] == ["layers", "endpoints"]

    def test_analyze_changes_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "analyze_changes")
        assert tool["inputSchema"]["required"] == ["mode"]
        modes = tool["inputSchema"]["properties"]["mode"]["enum"]
        assert set(modes) == {"pr_review", "impact", "impact_scope", "wiki_pr_impact"}

    def test_get_insights_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "get_insights")
        types = tool["inputSchema"]["properties"]["type"]["enum"]
        assert types == ["dashboard", "graph", "all"]

    def test_all_tools_have_description(self):
        for tool in MCP_TOOLS_MANIFEST:
            assert "description" in tool
            assert len(tool["description"]) > 10
