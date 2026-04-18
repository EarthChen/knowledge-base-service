"""MCP rag_business_search deprecation and rag_query entity_type enhancement."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import MCP_TOOLS_MANIFEST, KnowledgeBaseMCPHandler
from query.hybrid_query import HybridResult
from query.semantic_query import SemanticResult


def _manifest_tool(name: str) -> dict:
    return next(t for t in MCP_TOOLS_MANIFEST if t["name"] == name)


class TestRagBusinessSearchDeprecation:
    def test_manifest_description_marked_deprecated(self) -> None:
        tool = _manifest_tool("rag_business_search")
        assert tool["description"].startswith("[DEPRECATED] ")

    def test_manifest_input_schema_has_deprecated_extension(self) -> None:
        tool = _manifest_tool("rag_business_search")
        schema = tool["inputSchema"]
        assert schema.get("_deprecated") == "Use rag_query with entity_type parameter instead"

    @pytest.mark.asyncio
    async def test_handler_response_includes_deprecated_field(self) -> None:
        hybrid = MagicMock()
        hybrid.semantic.search_business_flows = AsyncMock(
            return_value=SemanticResult(matches=[], query_text="q", total=0),
        )
        hybrid.semantic.search_business_concepts = AsyncMock(
            return_value=SemanticResult(matches=[], query_text="q", total=0),
        )
        graph = MagicMock()
        graph.find_business_flow = AsyncMock(return_value=MagicMock(data=[]))

        handler = KnowledgeBaseMCPHandler(
            hybrid_svc=hybrid,
            graph_svc=graph,
            indexer=MagicMock(),
        )
        out = await handler.handle_rag_business_search({"query": "test", "search_type": "flow"})
        assert "_deprecated" in out
        assert out["_deprecated"] == "Use rag_query with entity_type parameter instead"


class TestRagQueryEntityType:
    def test_manifest_has_entity_type_property(self) -> None:
        tool = _manifest_tool("rag_query")
        props = tool["inputSchema"]["properties"]
        assert "entity_type" in props
        assert "entity_type" not in tool["inputSchema"].get("required", [])

    @pytest.mark.asyncio
    async def test_backward_compatible_without_entity_type(self) -> None:
        hybrid = MagicMock()
        hybrid.search_with_context = AsyncMock(
            return_value=HybridResult(
                semantic_matches=[{"name": "foo", "type": "Function"}],
                graph_context=[],
                query_text="find foo",
                total=1,
            ),
        )
        handler = KnowledgeBaseMCPHandler(
            hybrid_svc=hybrid,
            graph_svc=MagicMock(),
            indexer=MagicMock(),
        )
        result = await handler.handle_rag_query({"query": "find foo", "k": 5, "expand_depth": 2})

        hybrid.search_with_context.assert_awaited_once_with("find foo", k=5, expand_depth=2)
        assert result["query"] == "find foo"
        assert len(result["semantic_matches"]) == 1
        assert result["semantic_matches"][0]["name"] == "foo"
        assert result["total_results"] == 1

    @pytest.mark.asyncio
    async def test_entity_type_flow_searches_business_flows(self) -> None:
        hybrid = MagicMock()
        hybrid.search_with_context = AsyncMock()
        flow_match = {"name": "UserCheckout", "type": "BusinessFlow", "score": 0.9}
        hybrid.semantic.search_business_flows = AsyncMock(
            return_value=SemanticResult(matches=[flow_match], query_text="checkout", total=1),
        )
        graph = MagicMock()
        graph.find_business_flow = AsyncMock(return_value=MagicMock(data=[{"fn": "placeOrder"}]))

        handler = KnowledgeBaseMCPHandler(
            hybrid_svc=hybrid,
            graph_svc=graph,
            indexer=MagicMock(),
        )
        result = await handler.handle_rag_query(
            {"query": "checkout", "k": 3, "entity_type": "flow"},
        )

        hybrid.semantic.search_business_flows.assert_awaited_once_with("checkout", 3)
        hybrid.search_with_context.assert_not_called()
        assert result["query"] == "checkout"
        assert len(result["semantic_matches"]) == 1
        assert result["semantic_matches"][0]["name"] == "UserCheckout"
        graph.find_business_flow.assert_awaited()
