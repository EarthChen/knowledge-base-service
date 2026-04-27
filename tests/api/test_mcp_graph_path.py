def test_graph_path_in_mcp_tools() -> None:
    from api.mcp_server import MCP_TOOLS_MANIFEST

    names = {t["name"] for t in MCP_TOOLS_MANIFEST}
    assert "graph_path" in names
