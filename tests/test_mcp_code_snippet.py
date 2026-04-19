"""Tests for MCP get_code_snippet tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler


def _handler_with_store(store: MagicMock) -> KnowledgeBaseMCPHandler:
    return KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=store,
        wiki_handler=MagicMock(),
    )


@pytest.mark.asyncio
async def test_handle_get_code_snippet_valid_uid() -> None:
    store = MagicMock()
    row = {
        "uid": "fn-abc",
        "name": "process",
        "file": "app/service.py",
        "repository": "my-repo",
        "start_line": 10,
        "end_line": 25,
        "type": "Function",
        "code_snippet": "def process():\n    return 1\n",
        "signature": "def process() -> int:",
        "docstring": "Run process.",
        "language": "python",
        "fqn": "app.service.process",
    }
    store.execute_query = AsyncMock(return_value=MagicMock(data=[row]))

    h = _handler_with_store(store)
    r = await h.handle_get_code_snippet({"node_uid": "fn-abc"})

    store.execute_query.assert_awaited_once()
    cypher, params = store.execute_query.await_args[0]
    assert "$uid" in cypher
    assert "Function" in cypher and "Class" in cypher
    assert params == {"uid": "fn-abc"}

    assert r == {
        "uid": "fn-abc",
        "name": "process",
        "file": "app/service.py",
        "repository": "my-repo",
        "start_line": 10,
        "end_line": 25,
        "type": "Function",
        "code_snippet": "def process():\n    return 1\n",
        "signature": "def process() -> int:",
        "docstring": "Run process.",
        "language": "python",
        "fqn": "app.service.process",
    }


@pytest.mark.asyncio
async def test_handle_get_code_snippet_missing_uid() -> None:
    h = _handler_with_store(MagicMock())
    for args in ({}, {"node_uid": ""}, {"node_uid": "   "}):
        r = await h.handle_get_code_snippet(args)
        assert r["error"]["code"] == "invalid_params"
        assert "node_uid" in r["error"]["message"].lower()


@pytest.mark.asyncio
async def test_handle_get_code_snippet_no_store() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
    )
    r = await h.handle_get_code_snippet({"node_uid": "x"})
    assert r["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_handle_get_code_snippet_not_found() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    h = _handler_with_store(store)
    r = await h.handle_get_code_snippet({"node_uid": "missing"})
    assert r["error"]["code"] == "not_found"
    assert "missing" in r["error"]["message"]


@pytest.mark.asyncio
async def test_get_code_snippet_dispatched_via_handle_tool_call() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[{
                "uid": "c1",
                "name": "Foo",
                "file": "m.py",
                "start_line": 1,
                "end_line": 5,
                "type": "Class",
                "code_snippet": "class Foo: pass",
                "signature": "class Foo:",
                "docstring": "",
                "language": "python",
                "fqn": "m.Foo",
            }],
        ),
    )
    h = _handler_with_store(store)
    r = await h.handle_tool_call("get_code_snippet", {"node_uid": "c1"})
    assert r.get("name") == "Foo"
    assert "error" not in r
