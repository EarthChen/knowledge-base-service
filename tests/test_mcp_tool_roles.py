"""Per-tool MCP role authorization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
    out = await h.handle_tool_call("rag_index", {"directory": "/tmp"}, token_info=viewer)

    assert "error" in out
    assert out["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_handle_tool_call_allows_editor_on_rag_index() -> None:
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )

    async def fake_rag_index(args, progress_callback=None):
        return {"mode": "full", "directory": "/x", "stats": {}}

    h.handle_rag_index = fake_rag_index  # type: ignore[method-assign]

    editor = TokenInfo(role=Role.EDITOR)
    out = await h.handle_tool_call("rag_index", {"directory": "/tmp"}, token_info=editor)

    assert "error" not in out
    assert out["mode"] == "full"


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
        return_value=MagicMock(
            semantic_matches=[],
            graph_context=[],
            query_text="q",
            confidence=0.0,
            no_results_reason="",
        ),
    )

    out = await h.handle_tool_call("rag_query", {"query": "test"}, token_info=None)
    assert "error" not in out


def test_editor_tools_minimum_role_map() -> None:
    assert MCP_TOOL_MIN_ROLE["rag_index"] == Role.EDITOR
    assert MCP_TOOL_MIN_ROLE["wiki_export_execute"] == Role.EDITOR
    assert TOOL_ROLES is MCP_TOOL_MIN_ROLE
