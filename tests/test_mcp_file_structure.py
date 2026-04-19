"""Tests for MCP get_file_structure tool."""

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
async def test_get_file_structure_valid_repository_tree() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {"path": "README.md", "type": "Document"},
                {"path": "src/main/App.java", "type": "Module"},
                {"path": "src/main/Util.java", "type": "Module"},
            ],
        ),
    )
    h = _handler_with_store(store)
    r = await h.handle_get_file_structure({"repository": "owner/repo"})

    assert "error" not in r
    assert r["repository"] == "owner/repo"
    assert r["total_files"] == 3
    tree = r["tree"]
    names = [e["name"] for e in tree]
    assert names == ["README.md", "src"]
    readme = next(x for x in tree if x["name"] == "README.md")
    assert readme["type"] == "Document"
    assert "children" not in readme
    src = next(x for x in tree if x["name"] == "src")
    assert "type" not in src
    main = src["children"][0]
    assert main["name"] == "main"
    leaf_names = sorted(c["name"] for c in main["children"])
    assert leaf_names == ["App.java", "Util.java"]
    by_name = {c["name"]: c for c in main["children"]}
    assert by_name["App.java"]["type"] == "Module"
    assert by_name["Util.java"]["type"] == "Module"

    store.execute_query.assert_awaited_once()
    _cy, params = store.execute_query.await_args[0]
    assert params == {"repo": "owner/repo"}
    assert "Module" in _cy and "Document" in _cy


@pytest.mark.asyncio
async def test_get_file_structure_path_prefix_filters() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {"path": "other/x.py", "type": "Module"},
                {"path": "src/a.py", "type": "Module"},
                {"path": "src/sub/b.py", "type": "Module"},
            ],
        ),
    )
    h = _handler_with_store(store)
    r = await h.handle_get_file_structure({
        "repository": "r",
        "path_prefix": "src",
    })
    assert r["total_files"] == 2
    names = [e["name"] for e in r["tree"]]
    assert names == ["src"]
    under_src = {c["name"] for c in r["tree"][0]["children"]}
    assert under_src == {"a.py", "sub"}
    sub_node = next(c for c in r["tree"][0]["children"] if c["name"] == "sub")
    assert {c["name"] for c in sub_node["children"]} == {"b.py"}


@pytest.mark.asyncio
async def test_get_file_structure_max_depth_limits_depth() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[{"path": "a/b/c/d.java", "type": "Module"}],
        ),
    )
    h = _handler_with_store(store)
    r = await h.handle_get_file_structure({"repository": "r", "max_depth": 2})
    assert r["total_files"] == 1
    # Build stops at depth 2 path segments (a, b only)
    assert len(r["tree"]) == 1
    assert r["tree"][0]["name"] == "a"
    assert len(r["tree"][0]["children"]) == 1
    assert r["tree"][0]["children"][0]["name"] == "b"
    assert "children" not in r["tree"][0]["children"][0]


@pytest.mark.asyncio
async def test_get_file_structure_empty_repository_error() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    h = _handler_with_store(store)
    for args in ({}, {"repository": ""}, {"repository": "   "}):
        r = await h.handle_get_file_structure(args)
        assert r["error"]["code"] == "invalid_params"
        assert "repository" in r["error"]["message"].lower()
    store.execute_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_file_structure_no_store() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
    )
    r = await h.handle_get_file_structure({"repository": "x/y"})
    assert r["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_get_file_structure_no_files_empty_tree() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    h = _handler_with_store(store)
    r = await h.handle_get_file_structure({"repository": "empty/indexed"})
    assert "error" not in r
    assert r["tree"] == []
    assert r["total_files"] == 0
    assert r["repository"] == "empty/indexed"


@pytest.mark.asyncio
async def test_get_file_structure_dispatched_via_handle_tool_call() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"path": "x.py", "type": "Module"}]),
    )
    h = _handler_with_store(store)
    r = await h.handle_tool_call("get_file_structure", {"repository": "p/q"})
    assert "error" not in r
    assert r["total_files"] == 1
    assert r["tree"][0]["name"] == "x.py"
