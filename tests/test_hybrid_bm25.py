"""BM25 integration tests for HybridQueryService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from query.hybrid_query import HybridQueryService


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.keyword_search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_semantic():
    svc = AsyncMock()
    result = MagicMock()
    result.matches = []
    svc.search_all = AsyncMock(return_value=result)
    return svc


@pytest.fixture
def mock_graph():
    svc = AsyncMock()
    svc.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_class_methods = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_file_entities = AsyncMock(return_value=MagicMock(data=[]))
    return svc


@pytest.fixture
def mock_search_store():
    ss = AsyncMock()
    ss.fulltext_search = AsyncMock(return_value=[])
    return ss


class TestHybridBm25Integration:
    @pytest.mark.asyncio
    async def test_bm25_merged_into_rrf_when_enabled(
        self, mock_store, mock_semantic, mock_graph, mock_search_store,
    ):
        mock_store.keyword_search = AsyncMock(return_value=[
            {"name": "only_kw", "file": "a.py", "line": 1, "score": 1.0, "type": "Function",
             "uid": "u_kw", "signature": "", "docstring": "", "fqn": ""},
        ])
        sem_result = MagicMock()
        sem_result.matches = [
            {"name": "only_sem", "file": "b.py", "line": 1, "score": 0.9, "type": "Function"},
        ]
        mock_semantic.search_all = AsyncMock(return_value=sem_result)

        mock_search_store.fulltext_search = AsyncMock(return_value=[
            {"name": "bm_hit", "file": "c.py", "line": 9, "score": 2.5, "type": "Function",
             "uid": "u_bm", "signature": "", "docstring": "", "fqn": ""},
        ])

        svc = HybridQueryService(
            mock_store,
            mock_semantic,
            mock_graph,
            search_store=mock_search_store,
            enable_bm25=True,
            bm25_weight=1.2,
            query_expansion_enabled=False,
        )

        result = await svc.search_with_context("find auth helpers", k=10)

        mock_search_store.fulltext_search.assert_called()
        names = [m["name"] for m in result["results"]]
        assert "bm_hit" in names

    @pytest.mark.asyncio
    async def test_bm25_skipped_when_disabled(self, mock_store, mock_semantic, mock_graph, mock_search_store):
        svc = HybridQueryService(
            mock_store,
            mock_semantic,
            mock_graph,
            search_store=mock_search_store,
            enable_bm25=False,
            bm25_weight=1.2,
            query_expansion_enabled=False,
        )

        await svc.search_with_context("x", k=5)

        mock_search_store.fulltext_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_bm25_skipped_without_search_store(self, mock_store, mock_semantic, mock_graph):
        mock_store.keyword_search = AsyncMock(return_value=[])
        sem_result = MagicMock()
        sem_result.matches = []
        mock_semantic.search_all = AsyncMock(return_value=sem_result)

        svc = HybridQueryService(
            mock_store,
            mock_semantic,
            mock_graph,
            search_store=None,
            enable_bm25=True,
            query_expansion_enabled=False,
        )

        out = await svc.search_with_context("x", k=5)
        assert "results" in out

    @pytest.mark.asyncio
    async def test_mcp_enable_bm25_false_overrides(
        self, mock_store, mock_semantic, mock_graph, mock_search_store,
    ):
        svc = HybridQueryService(
            mock_store,
            mock_semantic,
            mock_graph,
            search_store=mock_search_store,
            enable_bm25=True,
            query_expansion_enabled=False,
        )

        await svc.search_with_context("x", k=5, enable_bm25=False)

        mock_search_store.fulltext_search.assert_not_called()
