from __future__ import annotations

from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST


def test_wiki_search_has_page_context_param():
    """wiki_search tool should accept optional page_context parameter."""
    tools = WIKI_MCP_TOOLS_MANIFEST
    wiki_search = None
    for tool in tools:
        if tool.get("name") == "wiki_search":
            wiki_search = tool
            break
    assert wiki_search is not None
    params = wiki_search.get("inputSchema", {}).get("properties", {})
    assert "page_context" in params
