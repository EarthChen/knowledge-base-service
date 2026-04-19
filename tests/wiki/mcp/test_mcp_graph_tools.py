"""MCP graph traversal tools — traverse_call_chain, find_impact_scope, analyze_pr_impact."""

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
        wiki_handler=wiki_handler,
    )


class TestTraverseCallChain:
    @pytest.mark.asyncio
    async def test_callees_direction(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        result = await wiki_handler.handle_traverse_call_chain(
            {"repository": "repo-a", "node_name": "foo", "direction": "callees"},
        )
        assert "error" not in result
        assert result["chain"][0]["edge_type"] == "CALLS"
        graph_port.traverse_call_chain.assert_awaited_once_with(
            repository="repo-a",
            node_name="foo",
            direction="callees",
            max_depth=3,
        )

    @pytest.mark.asyncio
    async def test_callers_direction(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        await wiki_handler.handle_traverse_call_chain(
            {"repository": "repo-a", "node_name": "bar", "direction": "callers"},
        )
        graph_port.traverse_call_chain.assert_awaited_once_with(
            repository="repo-a",
            node_name="bar",
            direction="callers",
            max_depth=3,
        )

    @pytest.mark.asyncio
    async def test_max_depth_capped(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        await wiki_handler.handle_traverse_call_chain(
            {"repository": "repo-a", "node_name": "x", "max_depth": 99},
        )
        call_kw = graph_port.traverse_call_chain.await_args.kwargs
        assert call_kw["max_depth"] == 5

    @pytest.mark.asyncio
    async def test_node_not_found_empty(self, graph_port: AsyncMock, wiki_pipeline: AsyncMock):
        graph_port.traverse_call_chain = AsyncMock(
            return_value={"root": None, "chain": [], "total_nodes": 0},
        )
        h = WikiMCPHandler(pipeline=wiki_pipeline, graph=graph_port)
        result = await h.handle_traverse_call_chain({"repository": "r", "node_name": "missing"})
        assert result["total_nodes"] == 0
        assert result["chain"] == []


class TestFindImpactScope:
    @pytest.mark.asyncio
    async def test_n_hop_expansion(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        result = await wiki_handler.handle_find_impact_scope(
            {"repository": "repo-a", "node_name": "fn"},
        )
        assert "error" not in result
        assert "0" in result["impact_by_hop"]
        assert "1" in result["impact_by_hop"]
        graph_port.find_impact_scope.assert_awaited_once_with(
            repository="repo-a",
            node_name="fn",
            max_hops=2,
        )

    @pytest.mark.asyncio
    async def test_max_hops_capped(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        await wiki_handler.handle_find_impact_scope(
            {"repository": "repo-a", "node_name": "fn", "max_hops": 10},
        )
        assert graph_port.find_impact_scope.await_args.kwargs["max_hops"] == 3


class TestAnalyzePrImpact:
    @pytest.mark.asyncio
    async def test_single_file_change(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        graph_port.analyze_pr_impact = AsyncMock(
            return_value={
                "affected_pages": [
                    {
                        "wiki_page_path": "modules/auth/AuthService",
                        "impact_level": "medium",
                        "reason": "1 entities directly modified",
                        "affected_entities": ["AuthService"],
                    },
                ],
                "summary": {"high_impact": 0, "medium_impact": 1, "total_affected_pages": 1},
            },
        )
        result = await wiki_handler.handle_analyze_pr_impact(
            {
                "repository": "repo-a",
                "changed_files": [{"path": "src/AuthService.java", "status": "M"}],
            },
        )
        assert "error" not in result
        assert result["summary"]["total_affected_pages"] == 1
        graph_port.analyze_pr_impact.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multi_file_impact_levels(self, wiki_handler: WikiMCPHandler, graph_port: AsyncMock):
        graph_port.analyze_pr_impact = AsyncMock(
            return_value={
                "affected_pages": [
                    {
                        "wiki_page_path": "modules/auth/AuthService",
                        "impact_level": "high",
                        "reason": "2 entities directly modified",
                        "affected_entities": ["AuthService", "TokenValidator"],
                    },
                    {
                        "wiki_page_path": "modules/util/Helpers",
                        "impact_level": "medium",
                        "reason": "1-hop impact",
                        "affected_entities": ["HelperFn"],
                    },
                ],
                "summary": {"high_impact": 1, "medium_impact": 1, "total_affected_pages": 2},
            },
        )
        result = await wiki_handler.handle_analyze_pr_impact(
            {
                "repository": "repo-a",
                "changed_files": [
                    {"path": "src/auth/AuthService.java", "status": "M"},
                    {"path": "src/util/Helpers.java", "status": "M"},
                ],
            },
        )
        assert result["summary"]["high_impact"] == 1
        assert result["summary"]["medium_impact"] == 1

    @pytest.mark.asyncio
    async def test_empty_changed_files(self, graph_port: AsyncMock, wiki_pipeline: AsyncMock):
        graph_port.analyze_pr_impact = AsyncMock(
            return_value={
                "affected_pages": [],
                "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
            },
        )
        h = WikiMCPHandler(pipeline=wiki_pipeline, graph=graph_port)
        result = await h.handle_analyze_pr_impact({"repository": "r", "changed_files": []})
        assert result["affected_pages"] == []


class TestValidationAndAvailability:
    @pytest.mark.asyncio
    async def test_repository_required(self, wiki_handler: WikiMCPHandler):
        r = await wiki_handler.handle_traverse_call_chain({"node_name": "x"})
        assert r["error"]["code"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_node_name_required(self, wiki_handler: WikiMCPHandler):
        r = await wiki_handler.handle_traverse_call_chain({"repository": "r"})
        assert r["error"]["code"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_graph_not_configured(self, wiki_pipeline: AsyncMock):
        h = WikiMCPHandler(pipeline=wiki_pipeline, graph=None)
        r = await h.handle_traverse_call_chain({"repository": "r", "node_name": "n"})
        assert r["error"]["code"] == "service_unavailable"

        r2 = await h.handle_find_impact_scope({"repository": "r", "node_name": "n"})
        assert r2["error"]["code"] == "service_unavailable"

        r3 = await h.handle_analyze_pr_impact(
            {"repository": "r", "changed_files": [{"path": "a.py", "status": "M"}]},
        )
        assert r3["error"]["code"] == "service_unavailable"


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_existing_wiki_tools_still_work(self, wiki_pipeline: AsyncMock, graph_port: AsyncMock):
        wiki = WikiMCPHandler(pipeline=wiki_pipeline, graph=graph_port)
        kb = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            wiki_handler=wiki,
        )
        await kb.handle_tool_call(
            "generate_wiki",
            {"repository": "demo-repo", "scope": "repo", "mode": "structure"},
        )
        wiki_pipeline.generate_wiki.assert_awaited()


class TestMCPRegistration:
    def test_graph_tools_in_wiki_manifest(self):
        names = {t["name"] for t in WIKI_MCP_TOOLS_MANIFEST}
        assert "traverse_call_chain" in names
        assert "find_impact_scope" in names
        assert "analyze_pr_impact" in names
        assert "wiki_lint" in names
        assert len(WIKI_MCP_TOOLS_MANIFEST) == 11

    def test_graph_tools_in_main_mcp_manifest(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "traverse_call_chain" in names
        assert "find_impact_scope" in names
        assert "analyze_pr_impact" in names


class TestDispatchViaKnowledgeBaseMCPHandler:
    @pytest.mark.asyncio
    async def test_dispatch_traverse_call_chain(self, kb_handler: KnowledgeBaseMCPHandler, graph_port: AsyncMock):
        await kb_handler.handle_tool_call(
            "traverse_call_chain",
            {"repository": "repo-a", "node_name": "fn"},
        )
        graph_port.traverse_call_chain.assert_awaited()
