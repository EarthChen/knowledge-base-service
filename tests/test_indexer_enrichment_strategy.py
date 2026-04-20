"""Tests for LLM enrichment_strategy behavior in IncrementalIndexer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import NodeLabel


def _make_settings(enrichment_strategy: str) -> MagicMock:
    fake = MagicMock()
    fake.llm.enrichment_strategy = enrichment_strategy
    return fake


@pytest.mark.asyncio
async def test_disabled_strategy_skips_enrichment() -> None:
    from indexer.incremental_indexer import IncrementalIndexer

    mock_store = MagicMock()
    mock_store.update_node_property = AsyncMock()

    mock_enricher = MagicMock()
    mock_enricher._gw = None
    mock_enricher.enrich_batch = AsyncMock(return_value=["should not be used"])

    indexer = IncrementalIndexer(
        store=mock_store,
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        enricher=mock_enricher,
    )

    items = [
        {
            "name": "UserService",
            "signature": "",
            "docstring": "",
            "code_snippet": "\n".join([f"    x_{i}()" for i in range(6)]),
            "file": "svc.py",
            "entity_kind": "class",
        }
    ]
    refs = [(NodeLabel.CLASS, "uid-1")]

    with patch("indexer.incremental_indexer.get_settings", return_value=_make_settings("disabled")):
        n = await indexer._enrich_from_items(items, refs, repo_id="r1")

    assert n == 0
    mock_enricher.enrich_batch.assert_not_called()
    mock_store.update_node_property.assert_not_called()


@pytest.mark.asyncio
async def test_core_only_strategy_filters_entities() -> None:
    from indexer.incremental_indexer import IncrementalIndexer

    mock_store = MagicMock()
    mock_store.update_node_property = AsyncMock()

    mock_enricher = MagicMock()
    mock_enricher._gw = None
    mock_enricher.enrich_batch = AsyncMock(return_value=["core summary"])

    indexer = IncrementalIndexer(
        store=mock_store,
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        enricher=mock_enricher,
    )

    items = [
        {
            "name": "UserService",
            "signature": "",
            "docstring": "",
            "code_snippet": "\n".join([f"    x_{i}()" for i in range(6)]),
            "file": "svc.py",
            "entity_kind": "class",
        },
        {
            "name": "normalize_ws",
            "signature": "",
            "docstring": "",
            "code_snippet": "def normalize_ws(s):\n    return s.strip()\n",
            "file": "util.py",
            "entity_kind": "function",
        },
    ]
    refs = [(NodeLabel.CLASS, "uid-core"), (NodeLabel.FUNCTION, "uid-util")]

    with patch("indexer.incremental_indexer.get_settings", return_value=_make_settings("core_only")):
        n = await indexer._enrich_from_items(items, refs, repo_id="r1")

    assert n == 1
    mock_enricher.enrich_batch.assert_called_once()
    (sent_items,), _kwargs = mock_enricher.enrich_batch.call_args
    assert len(sent_items) == 1
    assert sent_items[0]["name"] == "UserService"
    mock_store.update_node_property.assert_awaited_once()
    u_call = mock_store.update_node_property.await_args
    assert u_call.args[1] == "uid-core"
