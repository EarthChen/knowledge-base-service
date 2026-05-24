"""Incremental indexer COSMETIC vs STRUCTURAL path tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from indexer.chunk_hash import apply_content_hash_to_nodes
from indexer.structural_hash import compute_structural_hash
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel


def _make_incremental_indexer(
    store: MagicMock,
    builder: MagicMock,
    embed_gen: MagicMock | None = None,
):
    from indexer.incremental_indexer import IncrementalIndexer

    return IncrementalIndexer(
        store=store,
        graph_builder=builder,
        embedding_gen=embed_gen or MagicMock(),
    )


def _code_nodes() -> tuple[list[GraphNode], list[GraphEdge]]:
    fn = GraphNode(
        label=NodeLabel.FUNCTION,
        properties={
            "name": "doWork",
            "signature": "def doWork():",
            "file": "f.py",
            "start_line": 1,
            "docstring": "doc",
            "code_snippet": "def doWork():\n    pass",
        },
    )
    mod = GraphNode(
        label=NodeLabel.MODULE,
        properties={"name": "f", "path": "f.py", "language": "python", "file": "f.py"},
    )
    apply_content_hash_to_nodes([fn])
    return [mod, fn], []


@pytest.mark.asyncio
async def test_incremental_cosmetic_skip(tmp_path: Path) -> None:
    """Structural hash match skips batch_upsert but may refresh embeddings."""
    store = MagicMock()
    nodes, edges = _code_nodes()
    fn = nodes[1]
    structural = compute_structural_hash([fn], [], edges)

    store.get_chunk_hashes_for_files = AsyncMock(return_value={"old-hash": "stale"})
    store.get_node_uids_for_files = AsyncMock(return_value=set())
    store.get_module_structural_hash = AsyncMock(return_value=structural)
    store.update_module_metadata = AsyncMock()
    store.batch_upsert = AsyncMock()
    store.delete_parser_edges_for_files = AsyncMock()
    store.delete_nodes_by_uids = AsyncMock()
    store.resolve_cross_file_edges = AsyncMock(return_value={})
    store.set_node_embedding = AsyncMock()

    builder = MagicMock()
    builder.collect_relative_source_paths = MagicMock(return_value=[])
    builder.build_from_file = MagicMock(return_value=(nodes, edges))

    embed_gen = MagicMock()
    indexer = _make_incremental_indexer(store, builder, embed_gen)

    fpath = "f.py"
    (tmp_path / fpath).write_text("def doWork():\n    pass\n", encoding="utf-8")

    with (
        patch.object(indexer, "_get_changed_files", AsyncMock(return_value=[(fpath, "M")])),
        patch.object(
            indexer,
            "_generate_and_store_embeddings",
            AsyncMock(return_value=1),
        ) as mock_embed,
        patch("indexer.incremental_indexer.GraphEnricher") as mock_ge,
        patch("indexer.incremental_indexer.get_settings") as mock_settings,
    ):
        mock_settings.return_value.llm.enrichment_strategy = "disabled"
        mock_settings.return_value.wiki.auto_update_on_index = False
        mock_settings.return_value.exclude_dirs = set()
        mock_ge.return_value.enrich = AsyncMock(return_value={})

        await indexer.index_incremental(str(tmp_path))

    store.batch_upsert.assert_not_awaited()
    store.update_module_metadata.assert_awaited_once()
    mock_embed.assert_awaited_once()


@pytest.mark.asyncio
async def test_incremental_cosmetic_with_embedding_update(tmp_path: Path) -> None:
    """COSMETIC path updates embeddings when content_hash changes but structure is unchanged."""
    store = MagicMock()
    nodes, edges = _code_nodes()
    fn = nodes[1]
    fn.properties["docstring"] = "updated docstring"
    apply_content_hash_to_nodes([fn])
    new_content_hash = fn.properties["content_hash"]
    assert new_content_hash is not None

    structural = compute_structural_hash([fn], [], edges)
    old_content_hash = "stale-hash-not-matching-new-docstring"
    assert old_content_hash != new_content_hash

    store.get_chunk_hashes_for_files = AsyncMock(return_value={fn.uid: old_content_hash})
    store.get_node_uids_for_files = AsyncMock(return_value=set())
    store.get_module_structural_hash = AsyncMock(return_value=structural)
    store.update_module_metadata = AsyncMock()
    store.batch_upsert = AsyncMock()
    store.delete_parser_edges_for_files = AsyncMock()
    store.delete_nodes_by_uids = AsyncMock()
    store.resolve_cross_file_edges = AsyncMock(return_value={})
    store.set_node_embedding = AsyncMock()

    builder = MagicMock()
    builder.collect_relative_source_paths = MagicMock(return_value=[])
    builder.build_from_file = MagicMock(return_value=(nodes, edges))

    embed_gen = MagicMock()
    indexer = _make_incremental_indexer(store, builder, embed_gen)

    fpath = "f.py"
    (tmp_path / fpath).write_text('def doWork():\n    """updated docstring"""\n    pass\n', encoding="utf-8")

    with (
        patch.object(indexer, "_get_changed_files", AsyncMock(return_value=[(fpath, "M")])),
        patch.object(
            indexer,
            "_generate_and_store_embeddings",
            AsyncMock(return_value=1),
        ) as mock_embed,
        patch("indexer.incremental_indexer.GraphEnricher") as mock_ge,
        patch("indexer.incremental_indexer.get_settings") as mock_settings,
    ):
        mock_settings.return_value.llm.enrichment_strategy = "disabled"
        mock_settings.return_value.wiki.auto_update_on_index = False
        mock_settings.return_value.exclude_dirs = set()
        mock_ge.return_value.enrich = AsyncMock(return_value={})

        await indexer.index_incremental(str(tmp_path))

    store.batch_upsert.assert_not_awaited()
    store.update_module_metadata.assert_awaited_once()
    mock_embed.assert_awaited_once()
    embed_nodes = mock_embed.call_args[0][0]
    assert len(embed_nodes) == 1
    assert embed_nodes[0].uid == fn.uid
    assert embed_nodes[0].properties["content_hash"] == new_content_hash


@pytest.mark.asyncio
async def test_incremental_structural_path(tmp_path: Path) -> None:
    """Structural hash mismatch runs full batch_upsert and stores hash on Module."""
    store = MagicMock()
    nodes, edges = _code_nodes()
    fn = nodes[1]
    new_structural = compute_structural_hash([fn], [], edges)

    store.get_chunk_hashes_for_files = AsyncMock(return_value={})
    store.get_node_uids_for_files = AsyncMock(return_value=set())
    store.get_module_structural_hash = AsyncMock(return_value="different-old-hash")
    store.update_module_metadata = AsyncMock()
    store.batch_upsert = AsyncMock()
    store.delete_parser_edges_for_files = AsyncMock()
    store.delete_nodes_by_uids = AsyncMock()
    store.resolve_cross_file_edges = AsyncMock(return_value={})
    store.set_node_embedding = AsyncMock()

    builder = MagicMock()
    builder.collect_relative_source_paths = MagicMock(return_value=[])
    builder.build_from_file = MagicMock(return_value=(nodes, edges))

    indexer = _make_incremental_indexer(store, builder)

    fpath = "f.py"
    (tmp_path / fpath).write_text("def doWork():\n    pass\n", encoding="utf-8")

    with (
        patch.object(indexer, "_get_changed_files", AsyncMock(return_value=[(fpath, "M")])),
        patch.object(indexer, "_generate_and_store_embeddings", AsyncMock(return_value=0)),
        patch("indexer.incremental_indexer.GraphEnricher") as mock_ge,
        patch("indexer.incremental_indexer.get_settings") as mock_settings,
    ):
        mock_settings.return_value.llm.enrichment_strategy = "disabled"
        mock_settings.return_value.wiki.auto_update_on_index = False
        mock_settings.return_value.exclude_dirs = set()
        mock_ge.return_value.enrich = AsyncMock(return_value={})

        await indexer.index_incremental(str(tmp_path))

    store.batch_upsert.assert_awaited_once()
    mod = nodes[0]
    assert mod.properties.get("structural_hash") == new_structural


@pytest.mark.asyncio
async def test_structural_hash_exception_fallback(tmp_path: Path) -> None:
    """If get_module_structural_hash raises, process file as STRUCTURAL."""
    store = MagicMock()
    nodes, edges = _code_nodes()

    store.get_chunk_hashes_for_files = AsyncMock(return_value={})
    store.get_node_uids_for_files = AsyncMock(return_value=set())
    store.get_module_structural_hash = AsyncMock(side_effect=Exception("DB error"))
    store.update_module_metadata = AsyncMock()
    store.batch_upsert = AsyncMock()
    store.delete_parser_edges_for_files = AsyncMock()
    store.delete_nodes_by_uids = AsyncMock()
    store.resolve_cross_file_edges = AsyncMock(return_value={})

    builder = MagicMock()
    builder.collect_relative_source_paths = MagicMock(return_value=[])
    builder.build_from_file = MagicMock(return_value=(nodes, edges))

    indexer = _make_incremental_indexer(store, builder)

    fpath = "f.py"
    (tmp_path / fpath).write_text("def doWork():\n    pass\n", encoding="utf-8")

    with (
        patch.object(indexer, "_get_changed_files", AsyncMock(return_value=[(fpath, "M")])),
        patch.object(indexer, "_generate_and_store_embeddings", AsyncMock(return_value=0)),
        patch("indexer.incremental_indexer.GraphEnricher") as mock_ge,
        patch("indexer.incremental_indexer.get_settings") as mock_settings,
    ):
        mock_settings.return_value.llm.enrichment_strategy = "disabled"
        mock_settings.return_value.wiki.auto_update_on_index = False
        mock_settings.return_value.exclude_dirs = set()
        mock_ge.return_value.enrich = AsyncMock(return_value={})

        await indexer.index_incremental(str(tmp_path))

    store.batch_upsert.assert_awaited_once()
