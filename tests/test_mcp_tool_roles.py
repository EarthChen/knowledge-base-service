"""Per-tool MCP role authorization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.mcp_server import MCP_TOOL_MIN_ROLE, TOOL_ROLES, KnowledgeBaseMCPHandler
from auth import Role, TokenInfo


@pytest.mark.asyncio
async def test_handle_tool_call_forbids_viewer_on_editor_tool() -> None:
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )

    viewer = TokenInfo(role=Role.VIEWER)
    out = await h.handle_tool_call("wiki_export", {"repository": "r", "target_dir": "/tmp"}, token_info=viewer)

    assert "error" in out
    assert out["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_handle_tool_call_skips_role_check_when_no_token_info() -> None:
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )

    hybrid = h._hybrid
    hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "q",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )

    out = await h.handle_tool_call("rag_query", {"query": "test"}, token_info=None)
    assert "error" not in out


@pytest.mark.asyncio
async def test_handle_tool_call_require_auth_blocks_elevated_tools_without_token() -> None:
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=MagicMock(),
    )
    h._wiki.handle_wiki_export = AsyncMock(return_value={"ok": True})
    fake_settings = MagicMock()
    fake_settings.require_auth = True
    with patch("api.mcp_server.get_settings", return_value=fake_settings):
        out = await h.handle_tool_call(
            "wiki_export",
            {"repository": "r", "target_dir": "/tmp"},
            token_info=None,
        )
    assert "error" in out
    assert out["error"]["code"] == "forbidden"
    assert "Authentication required" in out["error"]["message"]
    h._wiki.handle_wiki_export.assert_not_called()


@pytest.mark.asyncio
async def test_handle_tool_call_require_auth_allows_viewer_tools_without_token() -> None:
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )
    hybrid = h._hybrid
    hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "q",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )
    fake_settings = MagicMock()
    fake_settings.require_auth = True
    with patch("api.mcp_server.get_settings", return_value=fake_settings):
        out = await h.handle_tool_call("rag_query", {"query": "test"}, token_info=None)
    assert "error" not in out


@pytest.mark.asyncio
async def test_rag_graph_raw_cypher_rejects_mutating() -> None:
    graph = AsyncMock()
    graph.execute_raw = AsyncMock()
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        graph,
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )
    out = await h.handle_rag_graph(
        {"query_type": "raw_cypher", "cypher": "CREATE (n:Node {id: 1})"},
    )
    assert "error" in out
    assert out["error"]["code"] == "forbidden"
    graph.execute_raw.assert_not_called()


@pytest.mark.asyncio
async def test_rag_graph_raw_cypher_allows_read_only() -> None:
    graph = AsyncMock()
    graph.execute_raw = AsyncMock(return_value=MagicMock(data=[{"n": 1}]))
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        graph,
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )
    out = await h.handle_rag_graph(
        {"query_type": "raw_cypher", "cypher": "MATCH (n) RETURN n LIMIT 1"},
    )
    assert "error" not in out
    assert out["type"] == "raw_cypher"
    graph.execute_raw.assert_awaited_once()


@pytest.mark.asyncio
async def test_rag_graph_call_chain_depth_clamped_high() -> None:
    graph = AsyncMock()
    graph.find_call_chain = AsyncMock(
        return_value=MagicMock(data=[], params={"_edges": []}),
    )
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        graph,
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )
    await h.handle_rag_graph(
        {"query_type": "call_chain", "name": "foo", "depth": 500},
    )
    assert graph.find_call_chain.await_args.kwargs["depth"] == 10


@pytest.mark.asyncio
async def test_rag_graph_depth_invalid_type_errors() -> None:
    graph = AsyncMock()
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        graph,
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )
    out = await h.handle_rag_graph(
        {"query_type": "call_chain", "name": "foo", "depth": "nope"},
    )
    assert "error" in out
    assert out["error"]["code"] == "invalid_params"
    graph.find_call_chain.assert_not_called()


def test_editor_tools_minimum_role_map() -> None:
    assert MCP_TOOL_MIN_ROLE["wiki_export"] == Role.EDITOR
    assert "rag_index" not in MCP_TOOL_MIN_ROLE
    assert TOOL_ROLES is MCP_TOOL_MIN_ROLE
