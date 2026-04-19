"""MCP task_status tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler


@pytest.mark.asyncio
async def test_task_status_requires_lookup() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
        task_status_fn=None,
    )
    r = await h.handle_tool_call("task_status", {"task_id": "abc"})
    assert r["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_task_status_missing_task_id() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
        task_status_fn=lambda _tid: {"task_id": "x"},
    )
    r = await h.handle_tool_call("task_status", {})
    assert r["error"]["code"] == "invalid_params"


@pytest.mark.asyncio
async def test_task_status_not_found() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
        task_status_fn=lambda _tid: None,
    )
    r = await h.handle_tool_call("task_status", {"task_id": "missing"})
    assert r["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_task_status_returns_payload() -> None:
    payload = {"task_id": "t1", "status": "running", "mode": "full"}

    def _lookup(task_id: str):
        assert task_id == "t1"
        return payload

    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
        task_status_fn=_lookup,
    )
    r = await h.handle_tool_call("task_status", {"task_id": "t1"})
    assert r == payload
