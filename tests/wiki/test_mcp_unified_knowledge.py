from __future__ import annotations

from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST


def test_unified_knowledge_query_in_manifest():
    """unified_knowledge_query tool should exist in manifest."""
    tools = WIKI_MCP_TOOLS_MANIFEST
    found = any(t.get("name") == "unified_knowledge_query" for t in tools)
    assert found, "unified_knowledge_query not found in MCP tools manifest"


def test_unified_knowledge_query_params():
    tools = WIKI_MCP_TOOLS_MANIFEST
    tool = next(t for t in tools if t.get("name") == "unified_knowledge_query")
    props = tool.get("inputSchema", {}).get("properties", {})
    assert "question" in props
    assert "scope" in props
