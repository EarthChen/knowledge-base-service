"""MCP graph traversal — internal wiki handlers and analyze_changes dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler, MCP_TOOLS_MANIFEST
from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST, WikiMCPHandler


@pytest.fixture
def wiki_pipeline() -> AsyncMock:
    p = AsyncMock()
    p.generate_wiki = AsyncMock(return_value=[])
    p.get_wiki_page = AsyncMock(return_value=None)
    p.list_wiki_pages = AsyncMock(return_value={"repository": "r", "tree": {}, "total_pages": 0})
    p.search_wiki = AsyncMock(return_value={"results": [], "total": 0})
    p.ask_about_code = AsyncMock(return_value={"content": "x"})
    return p


@pytest.fixture
def graph_port() -> AsyncMock:
    g = AsyncMock()
    g.traverse_call_chain = AsyncMock(
        return_value={
            "root": {"name": "rootFn", "type": "Function", "file": "a.py", "line": 1},
            "chain": [
                {
                    "depth": 1,
                    "node": {"name": "callee", "type": "Function", "file": "b.py", "line": 2},
                    "edge_type": "CALLS",
                    "wiki_page_path": "modules/x",
                },
            ],
            "total_nodes": 2,
        },
    )
    g.find_impact_scope = AsyncMock(
        return_value={
            "target": {"name": "t", "type": "Function", "file": "f.py", "line": 1},
            "impact_by_hop": {
                "0": [{"name": "t", "type": "Function", "wiki_page": "p1"}],
                "1": [{"name": "u", "type": "Function", "wiki_page": "p2"}],
            },
            "affected_wiki_pages": ["p1", "p2"],
            "total_affected": 2,
        },
    )
    g.analyze_pr_impact = AsyncMock(
        return_value={
            "affected_pages": [],
            "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
        },
    )
    return g


@pytest.fixture
def wiki_handler(wiki_pipeline: AsyncMock, graph_port: AsyncMock) -> WikiMCPHandler:
    return WikiMCPHandler(pipeline=wiki_pipeline, graph=graph_port)


@pytest.fixture
def kb_handler(wiki_handler: WikiMCPHandler) -> KnowledgeBaseMCPHandler:
    return KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=MagicMock(),
        wiki_handler=wiki_handler,
    )


class TestWikiGraphHandlers:
    @pytest.mark.asyncio
    async def test_traverse_call_chain_still_available_on_handler(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        result = await wiki_handler.handle_traverse_call_chain(
            {"repository": "repo-a", "node_name": "foo", "direction": "callees"},
        )
        assert "error" not in result
        graph_port.traverse_call_chain.assert_awaited_once_with(
            repository="repo-a",
            node_name="foo",
            direction="callees",
            max_depth=3,
        )

    @pytest.mark.asyncio
    async def test_find_impact_scope_via_analyze_changes(
        self, kb_handler: KnowledgeBaseMCPHandler, graph_port: AsyncMock,
    ):
        r = await kb_handler.handle_tool_call(
            "analyze_changes",
            {"mode": "impact_scope", "repository": "repo-a", "node_name": "fn"},
        )
        assert "error" not in r
        graph_port.find_impact_scope.assert_awaited_once_with(
            repository="repo-a",
            node_name="fn",
            max_hops=2,
        )

    @pytest.mark.asyncio
    async def test_wiki_pr_impact_via_analyze_changes(
        self, kb_handler: KnowledgeBaseMCPHandler, graph_port: AsyncMock,
    ):
        await kb_handler.handle_tool_call(
            "analyze_changes",
            {
                "mode": "wiki_pr_impact",
                "repository": "repo-a",
                "changed_files": [{"path": "src/a.py", "status": "M"}],
            },
        )
        graph_port.analyze_pr_impact.assert_awaited_once()


class TestMCPRegistration:
    def test_wiki_manifest_is_trimmed(self):
        names = {t["name"] for t in WIKI_MCP_TOOLS_MANIFEST}
        assert names == {
            "get_wiki_page",
            "list_wiki_pages",
            "search_wiki",
            "wiki_export",
            "wiki_get_tree",
            "wiki_get_related",
            "wiki_get_domain_overview",
            "wiki_get_snapshot",
        }
        assert len(WIKI_MCP_TOOLS_MANIFEST) == 8

    def test_analyze_changes_in_main_manifest(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "analyze_changes" in names
