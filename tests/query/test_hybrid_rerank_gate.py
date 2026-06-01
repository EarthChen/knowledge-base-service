"""Tests that hybrid search skips reranker for code-like queries when nl_only is set."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import RerankConfig
from query.hybrid_query import HybridQueryService
from query.reranker import Reranker


@pytest.fixture
def doc_map() -> dict[str, dict]:
    return {
        "f1:a.py:1": {
            "name": "f1",
            "file": "a.py",
            "line": 1,
            "score": 1.0,
            "type": "Function",
            "uid": "u1",
            "signature": "",
            "docstring": "",
        },
    }


@pytest.mark.asyncio
async def test_reranker_not_called_for_code_like_query_nl_only(doc_map) -> None:
    mock_store = MagicMock()
    mock_semantic = MagicMock()
    mock_graph = MagicMock()
    reranker = Reranker(RerankConfig(enabled=True, nl_only=True, device="cpu"))
    reranker.rerank_with_scores = AsyncMock(return_value=[])  # type: ignore[method-assign]

    svc = HybridQueryService(mock_store, mock_semantic, mock_graph, reranker=reranker)
    await svc._fuse_expansion_results(
        "com.example.AuthService",
        [[("f1:a.py:1", 1.0)]],
        [[("f1:a.py:1", 0.8)]],
        [1.5],
        [1.0],
        doc_map,
        k=5,
    )
    reranker.rerank_with_scores.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_reranker_called_for_natural_language_query_nl_only(doc_map) -> None:
    mock_store = MagicMock()
    mock_semantic = MagicMock()
    mock_graph = MagicMock()
    reranker = Reranker(RerankConfig(enabled=True, nl_only=True, device="cpu"))
    reranker.rerank_with_scores = AsyncMock(  # type: ignore[method-assign]
        return_value=[(doc_map["f1:a.py:1"], 0.9)]
    )

    svc = HybridQueryService(mock_store, mock_semantic, mock_graph, reranker=reranker)
    await svc._fuse_expansion_results(
        "how does authentication work",
        [[("f1:a.py:1", 1.0)]],
        [[("f1:a.py:1", 0.8)]],
        [1.5],
        [1.0],
        doc_map,
        k=5,
    )
    reranker.rerank_with_scores.assert_called_once()  # type: ignore[attr-defined]
