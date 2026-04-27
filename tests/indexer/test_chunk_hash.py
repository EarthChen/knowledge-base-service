"""Unit tests for chunk content hashing and incremental reindex edge cases."""

from __future__ import annotations

import pytest

from indexer.chunk_hash import (
    apply_content_hash_to_nodes,
    canonical_text_for_embed_hash,
    content_hash_for_node,
)
from store.schema import GraphNode, NodeLabel


class TestContentHashComputation:
    def test_chunk_hash_stable_and_stored(self) -> None:
        node = GraphNode(
            label=NodeLabel.CHUNK,
            uid="Chunk:src/a.py:foo:1:c0",
            properties={
                "name": "foo:chunk_0",
                "text": "// In foo: def foo():\n  return 1",
                "file": "src/a.py",
                "start_line": 1,
            },
        )
        h1 = content_hash_for_node(node)
        assert h1 and len(h1) == 64
        apply_content_hash_to_nodes([node])
        assert node.properties.get("content_hash") == h1

    def test_function_hash_changes_with_code(self) -> None:
        base = {
            "name": "f",
            "file": "m.py",
            "signature": "def f():",
            "docstring": "",
            "code_snippet": "def f():\n    return 1",
            "start_line": 1,
        }
        n1 = GraphNode(label=NodeLabel.FUNCTION, properties=dict(base))
        n2 = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={**base, "code_snippet": "def f():\n    return 2"},
        )
        assert content_hash_for_node(n1) != content_hash_for_node(n2)

    def test_module_not_hashed(self) -> None:
        n = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "m", "path": "x.py"},
        )
        assert content_hash_for_node(n) is None


class TestCanonicalTextMatchesFormat:
    def test_function_canonical_ignores_business_summary_property(self) -> None:
        a = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={
                "name": "g",
                "file": "f.py",
                "signature": "def g():",
                "docstring": "d",
                "code_snippet": "x",
                "start_line": 1,
                "business_summary": "should not affect",
            },
        )
        t = canonical_text_for_embed_hash(a)
        assert "should not" not in t
        assert "g" in t


@pytest.mark.asyncio
async def test_index_file_deletes_stale_node_uids() -> None:
    """Re-index removes graph nodes for UIDs that disappeared from the new parse result."""
    from unittest.mock import AsyncMock, MagicMock

    from indexer.incremental_indexer import IncrementalIndexer

    n = GraphNode(
        label=NodeLabel.FUNCTION,
        properties={
            "name": "a",
            "file": "t.py",
            "signature": "def a():",
            "docstring": "",
            "code_snippet": "def a():\n  pass",
            "start_line": 1,
        },
    )
    apply_content_hash_to_nodes([n])

    builder = MagicMock()
    builder.build_from_file = MagicMock(return_value=([n], []))
    store = MagicMock()
    store.get_chunk_hashes_for_files = AsyncMock(
        return_value={n.uid: n.properties.get("content_hash", "") or ""},
    )
    store.get_node_uids_for_files = AsyncMock(return_value={n.uid, "stale-uid-999"})
    store.delete_parser_edges_for_files = AsyncMock()
    store.delete_nodes_by_uids = AsyncMock()
    store.batch_upsert = AsyncMock()
    store.set_node_embedding = AsyncMock()
    store.update_node_property = AsyncMock()

    class FakeEmb:
        async def generate_for_code(self, _items: list) -> list:
            return [[0.0] * 4]

        async def generate_for_docs(self, _items: list) -> list:
            return [[0.0] * 4]

    idx = IncrementalIndexer(
        store,  # type: ignore[arg-type]
        builder,  # type: ignore[arg-type]
        FakeEmb(),  # type: ignore[arg-type]
    )
    await idx.index_file("t.py", store_path="t.py")
    store.delete_nodes_by_uids.assert_awaited()
    args, _ = store.delete_nodes_by_uids.call_args
    assert "stale-uid-999" in args[0]
    assert n.uid not in set(args[0])


@pytest.mark.asyncio
async def test_index_file_skips_embed_when_hash_matches() -> None:
    """``content_hash`` match skips embedding and leaves existing vectors untouched."""
    from unittest.mock import AsyncMock, MagicMock

    from indexer.incremental_indexer import IncrementalIndexer

    n = GraphNode(
        label=NodeLabel.FUNCTION,
        properties={
            "name": "a",
            "file": "t.py",
            "signature": "def a():",
            "docstring": "",
            "code_snippet": "def a():\n  pass",
            "start_line": 1,
        },
    )
    apply_content_hash_to_nodes([n])
    h = n.properties["content_hash"]

    builder = MagicMock()
    builder.build_from_file = MagicMock(return_value=([n], []))
    store = MagicMock()
    store.get_chunk_hashes_for_files = AsyncMock(return_value={n.uid: h})
    store.get_node_uids_for_files = AsyncMock(return_value={n.uid})
    store.delete_parser_edges_for_files = AsyncMock()
    store.delete_nodes_by_uids = AsyncMock()
    store.batch_upsert = AsyncMock()
    store.set_node_embedding = AsyncMock()

    class TrackingEmb:
        def __init__(self) -> None:
            self.code_calls = 0

        async def generate_for_code(self, items: list) -> list:  # noqa: ARG002
            self.code_calls += 1
            return [[0.0] * 4] * len(items)

        async def generate_for_docs(self, _items: list) -> list:
            return []

    tr = TrackingEmb()
    idx = IncrementalIndexer(
        store,  # type: ignore[arg-type]
        builder,  # type: ignore[arg-type]
        tr,  # type: ignore[arg-type]
    )
    await idx.index_file("t.py", store_path="t.py")
    assert tr.code_calls == 0
    store.set_node_embedding.assert_not_awaited()
