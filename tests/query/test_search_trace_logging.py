"""Structured trace logging for hybrid search and query routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

from query.hybrid_query import HybridQueryService
from query.query_router import route_query, should_rerank


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


def _events(cap: list[structlog.typing.EventDict], name: str) -> list[structlog.typing.EventDict]:
    return [e for e in cap if e.get("event") == name]


class TestQueryRouterTraceLogging:
    def test_route_query_logs_strategy(self) -> None:
        with capture_logs() as cap:
            strategy = route_query("how does authentication work")

        routed = _events(cap, "query_routed")
        assert len(routed) == 1
        assert routed[0]["query_type"] == strategy.query_type
        assert routed[0]["keyword_weight"] == strategy.keyword_weight
        assert routed[0]["semantic_weight"] == strategy.semantic_weight
        assert routed[0]["expand_graph"] == strategy.expand_graph

    def test_should_rerank_logs_decision(self) -> None:
        query = "how does authentication work in this codebase"
        with capture_logs() as cap:
            result = should_rerank(query)

        decisions = _events(cap, "rerank_decision")
        assert len(decisions) == 1
        assert decisions[0]["should_rerank"] is result
        assert decisions[0]["query_preview"] == query[:80]


@pytest.fixture
def mock_store() -> AsyncMock:
    store = AsyncMock()
    store.keyword_search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_semantic() -> AsyncMock:
    svc = AsyncMock()
    svc.search_all = AsyncMock(return_value=MagicMock(matches=[]))
    return svc


@pytest.fixture
def mock_graph() -> AsyncMock:
    svc = AsyncMock()
    svc.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_class_methods = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))
    return svc


@pytest.mark.asyncio
class TestHybridSearchTraceLogging:
    async def test_search_with_context_logs_entry_and_completion(
        self, mock_store: AsyncMock, mock_semantic: AsyncMock, mock_graph: AsyncMock,
    ) -> None:
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        query = "retry logic in payment service"

        with capture_logs() as cap:
            await svc.search_with_context(
                query,
                repository="my-repo",
                use_query_expansion=False,
                limit=10,
            )

        started = _events(cap, "search_started")
        assert len(started) == 1
        assert started[0]["query"] == query[:100]
        assert started[0]["repository"] == "my-repo"
        assert started[0]["use_child_chunks"] is False

        recall = _events(cap, "search_recall")
        assert len(recall) >= 1
        assert "kw_hits" in recall[0]
        assert "sem_hits" in recall[0]
        assert "bm25_hits" in recall[0]

        completed = _events(cap, "search_completed")
        assert len(completed) == 1
        assert completed[0]["total"] == 0
        assert "confidence" in completed[0]
        assert "no_results_reason" in completed[0]

    async def test_fuse_expansion_results_logs_fusion_summary(
        self, mock_store: MagicMock, mock_semantic: MagicMock, mock_graph: MagicMock,
    ) -> None:
        doc_map = {
            "f1:a.py:1": {
                "name": "f1",
                "file": "a.py",
                "line": 1,
                "type": "Function",
            },
        }
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)

        with capture_logs() as cap:
            await svc._fuse_expansion_results(
                "how does auth work",
                [[("f1:a.py:1", 1.0)]],
                [[("f1:a.py:1", 0.8)]],
                [1.5],
                [1.0],
                doc_map,
                k=5,
            )

        fused = _events(cap, "search_fused")
        assert len(fused) == 1
        assert fused[0]["candidates"] >= 1
        assert fused[0]["rerank_applied"] is False
