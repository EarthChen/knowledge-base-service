"""Tests for MCP server tool manifest and handler routing."""

from api.mcp_server import MCP_TOOLS_MANIFEST


class TestMCPToolsManifest:
    def test_has_three_tools(self):
        assert len(MCP_TOOLS_MANIFEST) == 3

    def test_tool_names(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert names == {"rag_query", "rag_graph", "rag_index"}

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

    def test_rag_index_schema(self):
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_index")
        schema = tool["inputSchema"]
        assert "directory" in schema["properties"]
        assert "directory" in schema["required"]
        assert "mode" in schema["properties"]
        assert schema["properties"]["mode"]["enum"] == ["full", "incremental"]

    def test_all_tools_have_description(self):
        for tool in MCP_TOOLS_MANIFEST:
            assert "description" in tool
            assert len(tool["description"]) > 10
