"""MCP search_architecture tool — endpoints mode (replaces list_endpoints)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler, MCP_TOOLS_MANIFEST


@pytest.mark.asyncio
async def test_search_architecture_endpoints_delegates_to_query() -> None:
    store = MagicMock()
    with patch(
        "query.endpoint_queries.query_all_endpoints",
        new=AsyncMock(
            return_value={
                "repository": "",
                "http_endpoints": [],
                "rpc_endpoints": [],
                "kafka_endpoints": [],
                "total": 0,
            },
        ),
    ) as qe:
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            store=store,
            wiki_handler=MagicMock(),
        )
        r = await h.handle_search_architecture({"mode": "endpoints"})
        assert "error" not in r
        qe.assert_awaited_once_with(store, "")


@pytest.mark.asyncio
async def test_search_architecture_endpoints_passes_repository() -> None:
    store = MagicMock()
    with patch(
        "query.endpoint_queries.query_all_endpoints",
        new=AsyncMock(return_value={"repository": "org/app", "total": 0}),
    ) as qe:
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            store=store,
            wiki_handler=MagicMock(),
        )
        await h.handle_search_architecture({"mode": "endpoints", "repository": "org/app"})
        qe.assert_awaited_once_with(store, "org/app")


def test_manifest_includes_search_architecture_endpoints_mode() -> None:
    tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "search_architecture")
    assert tool["inputSchema"]["properties"]["mode"]["enum"] == ["layers", "endpoints"]
