"""Tests for indexed_at stamping and index_freshness MCP tool."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.doc_indexer import DocumentIndexer
from indexer.tree_sitter_parser import TreeSitterParser


@pytest.fixture
def python_extensions() -> dict[str, list[str]]:
    return {"python": [".py"]}


def test_code_nodes_carry_indexed_at(tmp_path: Path, python_extensions: dict[str, list[str]]) -> None:
    src = tmp_path / "hello.py"
    src.write_text(
        "def foo():\n"
        '    """doc"""\n'
        "    return 1\n",
        encoding="utf-8",
    )

    parser = TreeSitterParser()
    builder = CodeGraphBuilder(parser, python_extensions)
    nodes, _edges = builder.build_from_file(str(src))

    assert nodes
    for n in nodes:
        ts = n.properties.get("indexed_at")
        assert isinstance(ts, str) and ts
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_document_nodes_carry_indexed_at(tmp_path: Path) -> None:
    doc_path = tmp_path / "readme.md"
    doc_path.write_text("# Title\n\nHello\n", encoding="utf-8")

    idx = DocumentIndexer(exclude_patterns=[])
    parsed = idx.parse_document(str(doc_path))
    nodes, _edges = idx.build_graph(parsed)

    assert nodes
    for n in nodes:
        ts = n.properties.get("indexed_at")
        assert isinstance(ts, str) and ts
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_index_freshness_tool_structure() -> None:
    store = MagicMock()
    store.get_repository_index_freshness = AsyncMock(
        return_value={
            "repository": "owner/repo",
            "last_indexed_at": "2026-04-01T12:00:00+00:00",
            "node_count": 42,
            "commit_sha": "abcd1234",
        },
    )

    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=store,
        wiki_handler=MagicMock(),
    )
    out = await h.handle_tool_call("index_freshness", {"repository": "owner/repo"})
    assert out == {
        "repository": "owner/repo",
        "last_indexed_at": "2026-04-01T12:00:00+00:00",
        "node_count": 42,
        "commit_sha": "abcd1234",
    }
    store.get_repository_index_freshness.assert_awaited_once_with("owner/repo")


@pytest.mark.asyncio
async def test_index_freshness_missing_repository_error() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=MagicMock(),
        wiki_handler=MagicMock(),
    )
    out = await h.handle_tool_call("index_freshness", {})
    assert out["error"]["code"] == "invalid_params"


@pytest.mark.asyncio
async def test_index_freshness_absent_repository_payload() -> None:
    store = MagicMock()
    store.get_repository_index_freshness = AsyncMock(
        return_value={
            "repository": "ghost/repo",
            "last_indexed_at": None,
            "node_count": 0,
            "commit_sha": None,
        },
    )

    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=store,
        wiki_handler=MagicMock(),
    )
    out = await h.handle_tool_call("index_freshness", {"repository": "ghost/repo"})
    assert out["last_indexed_at"] is None
    assert out["node_count"] == 0
    assert out["commit_sha"] is None
