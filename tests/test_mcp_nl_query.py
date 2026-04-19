"""Tests for NL→Cypher MCP integration."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import MCP_TOOLS_MANIFEST, KnowledgeBaseMCPHandler


def test_nl_query_in_rag_graph_enum():
    """nl_query must be in the rag_graph query_type enum."""
    rag_graph = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_graph")
    enum_vals = rag_graph["inputSchema"]["properties"]["query_type"]["enum"]
    assert "nl_query" in enum_vals


@pytest.mark.asyncio
async def test_handle_nl_query_success():
    """MCP dispatch routes nl_query to NLCypherService."""
    nl_cypher = MagicMock()
    nl_cypher.query = AsyncMock(return_value={
        "question": "find login",
        "cypher": "MATCH (f:Function) WHERE f.name = 'login' RETURN f LIMIT 10",
        "results": [{"f.name": "login"}],
        "total": 1,
        "attempt": 1,
    })

    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=MagicMock(),
        wiki_handler=MagicMock(),
        nl_cypher=nl_cypher,
    )

    r = await h.handle_rag_graph({"query_type": "nl_query", "name": "find login"})
    assert r["type"] == "nl_query"
    assert r["total"] == 1
    nl_cypher.query.assert_awaited_once_with("find login", repository=None)


@pytest.mark.asyncio
async def test_handle_nl_query_no_llm():
    """NL query without LLM returns service_unavailable."""
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=MagicMock(),
        wiki_handler=MagicMock(),
        nl_cypher=None,
    )

    r = await h.handle_rag_graph({"query_type": "nl_query", "name": "find login"})
    assert r["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_handle_nl_query_missing_question():
    """NL query without question returns invalid_params."""
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=MagicMock(),
        wiki_handler=MagicMock(),
        nl_cypher=MagicMock(),
    )

    r = await h.handle_rag_graph({"query_type": "nl_query", "name": ""})
    assert r["error"]["code"] == "invalid_params"
