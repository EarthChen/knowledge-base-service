from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST


def test_wiki_search_tool_name():
    names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_search" in names, f"Expected 'wiki_search' in {names}"


def test_search_wiki_alias_exists():
    from wiki.mcp_tools import WikiMCPHandler

    assert hasattr(WikiMCPHandler, "handle_wiki_search")
    assert hasattr(WikiMCPHandler, "handle_search_wiki")
