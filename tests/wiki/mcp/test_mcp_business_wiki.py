def test_wiki_get_tree_in_manifest():
    from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST

    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_tree" in tool_names


def test_wiki_get_related_in_manifest():
    from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST

    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_related" in tool_names


def test_wiki_get_domain_overview_in_manifest():
    from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST

    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_domain_overview" in tool_names
