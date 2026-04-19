"""Tests for HybridQueryService with RRF fusion."""

import pytest
from unittest.mock import AsyncMock, MagicMock

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


class TestHybridQueryRRF:
    @pytest.mark.asyncio
    async def test_empty_results(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("test query")
        assert result["results"] == []
        assert result["graph_context"] == []

    @pytest.mark.asyncio
    async def test_keyword_only_results(self, mock_store, mock_semantic, mock_graph):
        mock_store.keyword_search = AsyncMock(return_value=[
            {"name": "UserService", "file": "user.py", "line": 10, "score": 1.0, "type": "Class", "uid": "u1", "signature": "", "docstring": ""},
        ])
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("UserService", k=5)
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "UserService"
        assert result["results"][0]["match_source"] == "keyword"
        assert "confidence" in result["results"][0]
        assert result["results"][0]["confidence"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_semantic_only_results(self, mock_store, mock_semantic, mock_graph):
        sem_result = MagicMock()
        sem_result.matches = [
            {"name": "login", "file": "auth.py", "line": 5, "score": 0.85, "type": "Function"},
        ]
        mock_semantic.search_all = AsyncMock(return_value=sem_result)
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("authentication login")
        assert len(result["results"]) == 1
        assert result["results"][0]["match_source"] == "semantic"

    @pytest.mark.asyncio
    async def test_both_sources_rrf_fusion(self, mock_store, mock_semantic, mock_graph):
        """Both keyword and semantic hits should be fused via RRF."""
        mock_store.keyword_search = AsyncMock(return_value=[
            {"name": "funcA", "file": "a.py", "line": 1, "score": 1.0, "type": "Function", "uid": "u1", "signature": "", "docstring": ""},
            {"name": "funcB", "file": "b.py", "line": 2, "score": 0.8, "type": "Function", "uid": "u2", "signature": "", "docstring": ""},
        ])
        sem_result = MagicMock()
        sem_result.matches = [
            {"name": "funcB", "file": "b.py", "line": 2, "score": 0.9, "type": "Function"},
            {"name": "funcC", "file": "c.py", "line": 3, "score": 0.7, "type": "Function"},
        ]
        mock_semantic.search_all = AsyncMock(return_value=sem_result)
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("funcA funcB", k=5)
        names = [m["name"] for m in result["results"]]
        # funcB should appear only once (deduped)
        assert names.count("funcB") == 1
        # All three should be present
        assert set(names) == {"funcA", "funcB", "funcC"}

    @pytest.mark.asyncio
    async def test_rrf_ordering_differs_from_score_sort(self, mock_store, mock_semantic, mock_graph):
        """RRF should produce different ordering than simple score sort in some cases."""
        mock_store.keyword_search = AsyncMock(return_value=[
            {"name": "exact_match", "file": "a.py", "line": 1, "score": 0.5, "type": "Function", "uid": "u1", "signature": "", "docstring": ""},
        ])
        sem_result = MagicMock()
        sem_result.matches = [
            {"name": "semantic_hit", "file": "b.py", "line": 1, "score": 0.95, "type": "Function"},
            {"name": "exact_match", "file": "a.py", "line": 1, "score": 0.3, "type": "Function"},
        ]
        mock_semantic.search_all = AsyncMock(return_value=sem_result)
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("exact_match", k=5)
        # exact_match should be ranked higher due to appearing in both lists + keyword weight 1.5
        assert result["results"][0]["name"] == "exact_match"

    def test_doc_key_method(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        key = svc._doc_key({"name": "foo", "file": "bar.py", "line": 42})
        assert key == "foo:bar.py:42"

    @pytest.mark.asyncio
    async def test_with_reranker(self, mock_store, mock_semantic, mock_graph):
        """When reranker is present, should use position-aware blending."""
        mock_store.keyword_search = AsyncMock(return_value=[
            {"name": "f1", "file": "a.py", "line": 1, "score": 1.0, "type": "Function", "uid": "u1", "signature": "", "docstring": ""},
        ])
        sem_result = MagicMock()
        sem_result.matches = [
            {"name": "f2", "file": "b.py", "line": 1, "score": 0.8, "type": "Function"},
        ]
        mock_semantic.search_all = AsyncMock(return_value=sem_result)

        mock_reranker = AsyncMock()
        mock_reranker.rerank_with_scores = AsyncMock(return_value=[
            ({"name": "f2", "file": "b.py", "line": 1, "score": 0.8, "type": "Function", "match_source": "semantic"}, 0.95),
            ({"name": "f1", "file": "a.py", "line": 1, "score": 1.0, "type": "Function", "match_source": "keyword"}, 0.3),
        ])

        svc = HybridQueryService(mock_store, mock_semantic, mock_graph, reranker=mock_reranker)
        result = await svc.search_with_context("test", k=5)
        # Reranker was called
        mock_reranker.rerank_with_scores.assert_called_once()
        assert len(result["results"]) > 0
