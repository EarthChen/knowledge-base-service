"""Tests for MCP server tool manifest and handler routing."""

from api.mcp_server import MCP_TOOLS_MANIFEST


class TestMCPToolsManifest:
    def test_tool_count(self):
        assert len(MCP_TOOLS_MANIFEST) == 27

    def test_tool_names(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert names == {
            "rag_query",
            "rag_graph",
            "deep_search",
            "rag_index",
            "task_status",
            "list_documents",
            "get_document",
            "analyze_impact",
            "list_endpoints",
            "check_consistency",
            "review_pr",
            "build_context",
            "search_architecture",
            "code_quality",
            "dashboard_stats",
            "graph_insights",
            "generate_wiki",
            "get_wiki_page",
            "list_wiki_pages",
            "search_wiki",
            "ask_about_code",
            "traverse_call_chain",
            "find_impact_scope",
            "analyze_pr_impact",
            "wiki_lint",
            "wiki_export_preview",
            "wiki_export_execute",
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
        assert "git_url" in schema["properties"]
        assert "branch" in schema["properties"]
        assert "required" not in schema or schema.get("required") in (None, [])
        assert "mode" in schema["properties"]
        assert schema["properties"]["mode"]["enum"] == ["full", "incremental"]

    def test_task_status_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "task_status")
        schema = tool["inputSchema"]
        assert "task_id" in schema["properties"]
        assert schema["required"] == ["task_id"]

    def test_deep_search_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "deep_search")
        schema = tool["inputSchema"]
        assert "query" in schema["required"]
        assert "max_iterations" in schema["properties"]

    def test_list_documents_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "list_documents")
        assert "repository" in tool["inputSchema"]["properties"]

    def test_get_document_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "get_document")
        assert "doc_uid" in tool["inputSchema"]["required"]

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
