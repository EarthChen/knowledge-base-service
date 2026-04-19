"""Child-chunk hybrid path should apply query router keyword/semantic weights."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from query.hybrid_query import HybridQueryService
from query.query_router import SearchStrategy


@pytest.mark.asyncio
async def test_search_with_child_chunks_uses_route_query_weights() -> None:
    store = AsyncMock()
    store.keyword_search = AsyncMock(return_value=[])
    graph = AsyncMock()
    graph.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
    graph.find_class_methods = AsyncMock(return_value=MagicMock(data=[]))
    graph.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    graph.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))

    sem = AsyncMock()
    chunk_result = MagicMock()
    chunk_result.matches = [
        {
            "name": "f1",
            "file": "a.py",
            "line": 1,
            "score": 0.9,
            "type": "Function",
            "uid": "p1",
            "matched_excerpt": "x",
            "excerpt_lines": [1, 2],
        }
    ]
    sem.search_with_parent_context = AsyncMock(return_value=chunk_result)

    strategy = SearchStrategy(
        keyword_weight=0.2,
        semantic_weight=3.0,
        expand_graph=True,
        entity_priority=[],
        query_type="general",
    )

    mock_fuse = AsyncMock(
        return_value=[
            {
                "name": "f1",
                "file": "a.py",
                "line": 1,
                "type": "Function",
                "uid": "p1",
                "match_source": "chunk_semantic",
                "score": 0.5,
                "confidence": 0.5,
            }
        ],
    )

    svc = HybridQueryService(store, sem, graph, use_child_chunks=False)
    with patch("query.hybrid_query.route_query", return_value=strategy):
        with patch.object(svc, "_fuse_expansion_results", mock_fuse):
            await svc.search_with_context(
                "how does billing work",
                use_child_chunks=True,
                use_query_router=True,
            )

    mock_fuse.assert_called_once()
    args = mock_fuse.call_args[0]
    # Bound method mock may omit ``self`` from the recorded positional args.
    pos = args[1:] if args and args[0] is svc else args
    kw_weights, sem_weights = pos[3], pos[4]
    assert kw_weights == [strategy.keyword_weight]
    assert sem_weights == [strategy.semantic_weight]


@pytest.mark.asyncio
async def test_child_chunks_skips_graph_when_router_expand_graph_false() -> None:
    store = AsyncMock()
    store.keyword_search = AsyncMock(return_value=[
        {"name": "f1", "file": "a.py", "line": 1, "score": 1.0, "type": "Function", "uid": "u1"},
    ])
    graph = AsyncMock()
    sem = AsyncMock()
    chunk_result = MagicMock()
    chunk_result.matches = [
        {
            "name": "Foo",
            "file": "a.py",
            "line": 1,
            "score": 0.9,
            "text": "body",
            "parent_uid": "pu1",
            "parent_name": "Foo",
            "parent_label": "Function",
            "start_line": 1,
            "end_line": 2,
            "type": "Function",
            "uid": "pu1",
        },
    ]
    sem.search_with_parent_context = AsyncMock(return_value=chunk_result)

    strategy = SearchStrategy(
        keyword_weight=1.5,
        semantic_weight=1.0,
        expand_graph=False,
        entity_priority=[],
        query_type="general",
    )

    svc = HybridQueryService(store, sem, graph, use_child_chunks=False)
    with patch("query.hybrid_query.route_query", return_value=strategy):
        with patch.object(svc, "_expand_graph", AsyncMock()) as eg:
            await svc.search_with_context(
                "billing service",
                k=5,
                use_child_chunks=True,
                use_query_router=True,
            )

    eg.assert_not_called()
