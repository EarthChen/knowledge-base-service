from api.mcp_wiki_server import MCPWikiServer, TOOL_DEFINITIONS


def test_tool_definitions_exist():
    assert len(TOOL_DEFINITIONS) >= 5
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "wiki_search" in names
    assert "wiki_explain" in names
    assert "wiki_navigate" in names
    assert "wiki_qa" in names
    assert "wiki_impact" in names


def test_server_initialization():
    server = MCPWikiServer()
    assert server is not None
    assert hasattr(server, "handle_tool_call")
