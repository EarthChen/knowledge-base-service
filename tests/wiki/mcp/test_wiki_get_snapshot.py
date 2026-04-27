def test_wiki_get_snapshot_in_manifests():
    from api.mcp_wiki_server import TOOL_DEFINITIONS
    from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST

    t1 = {d["name"] for d in TOOL_DEFINITIONS}
    t2 = {d["name"] for d in WIKI_MCP_TOOLS_MANIFEST}
    assert "wiki_get_snapshot" in t1
    assert "wiki_get_snapshot" in t2
