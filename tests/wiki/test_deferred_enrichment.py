"""Deferred wiki-stage enrichment for missing business_summary."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from store.schema import NodeLabel
from wiki.deferred_enrichment import DeferredEnrichmentService


def _wrap_raw(rows: list[list[object]]) -> QueryResultWrapper:
    return QueryResultWrapper(data=[], raw=rows)


@pytest.mark.asyncio
async def test_enrich_remaining_calls_enricher() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=_wrap_raw(
            [
                [
                    "fn:1",
                    "process",
                    "def process():",
                    "doc",
                    "def process():\n"
                    + "\n".join(f"    step_{i}()" for i in range(5))
                    + "\n    return 1\n",
                    "app.py",
                    "Function",
                ],
            ],
        ),
    )
    store.update_node_property = AsyncMock()

    enricher = MagicMock()
    enricher.enrich_batch = AsyncMock(return_value=["Does the thing"])

    svc = DeferredEnrichmentService(store=store, enricher=enricher, embedding_gen=None)
    count = await svc.enrich_remaining("myrepo")

    assert count == 1
    enricher.enrich_batch.assert_awaited_once()
    store.update_node_property.assert_awaited_once_with(
        NodeLabel.FUNCTION,
        "fn:1",
        "business_summary",
        "Does the thing",
    )
    call = store.execute_query.await_args
    assert call is not None
    assert call.args[1]["repo"] == "myrepo"


@pytest.mark.asyncio
async def test_enrich_remaining_skips_trivial() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=_wrap_raw(
            [
                [
                    "c:1",
                    "MyClass",
                    "",
                    "",
                    "",
                    "m.py",
                    "Class",
                ],
                [
                    "f:2",
                    "__init__",
                    "def __init__(self):",
                    "",
                    "pass",
                    "m.py",
                    "Function",
                ],
            ],
        ),
    )
    store.update_node_property = AsyncMock()

    enricher = MagicMock()
    enricher.enrich_batch = AsyncMock(return_value=["Class summary"])

    svc = DeferredEnrichmentService(store=store, enricher=enricher, embedding_gen=None)
    count = await svc.enrich_remaining("r")

    assert count == 1
    enricher.enrich_batch.assert_awaited_once()
    sent = enricher.enrich_batch.await_args.args[0]
    assert len(sent) == 1
    assert sent[0]["entity_kind"] == "class"
    store.update_node_property.assert_awaited_once_with(
        NodeLabel.CLASS,
        "c:1",
        "business_summary",
        "Class summary",
    )


@pytest.mark.asyncio
async def test_enrich_remaining_empty() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=_wrap_raw([]))
    store.update_node_property = AsyncMock()
    enricher = MagicMock()
    enricher.enrich_batch = AsyncMock()

    svc = DeferredEnrichmentService(store=store, enricher=enricher, embedding_gen=None)
    assert await svc.enrich_remaining("r") == 0
    enricher.enrich_batch.assert_not_awaited()
    store.update_node_property.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_stale_embeddings() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=_wrap_raw(
            [
                [
                    "f:1",
                    "foo",
                    "summary text",
                    "x = 1",
                    "def foo(): pass",
                    "d",
                    "Function",
                ],
            ],
        ),
    )
    store.set_node_embedding = AsyncMock()

    emb = MagicMock()
    emb.generate_for_code = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    svc = DeferredEnrichmentService(store=store, enricher=MagicMock(), embedding_gen=emb)
    n = await svc.refresh_stale_embeddings("repo")

    assert n == 1
    emb.generate_for_code.assert_awaited_once()
    items = emb.generate_for_code.await_args.args[0]
    assert items[0]["name"] == "foo"
    assert items[0]["business_summary"] == "summary text"
    store.set_node_embedding.assert_awaited_once_with(
        "f:1",
        NodeLabel.FUNCTION,
        [0.1, 0.2, 0.3],
    )


@pytest.mark.asyncio
async def test_refresh_stale_embeddings_no_embedding_gen() -> None:
    store = MagicMock()
    svc = DeferredEnrichmentService(store=store, enricher=MagicMock(), embedding_gen=None)
    assert await svc.refresh_stale_embeddings("r") == 0
    store.execute_query.assert_not_called()
