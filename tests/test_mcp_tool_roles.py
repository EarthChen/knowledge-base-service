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


def test_editor_tools_minimum_role_map() -> None:
    assert MCP_TOOL_MIN_ROLE["wiki_export"] == Role.EDITOR
    assert "rag_index" not in MCP_TOOL_MIN_ROLE
    assert TOOL_ROLES is MCP_TOOL_MIN_ROLE
