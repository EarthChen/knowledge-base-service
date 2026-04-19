from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider

    llm = MagicMock(spec=LLMProvider)
    llm.complete_json = AsyncMock(
        side_effect=[
            {
                "intent": "impact_analysis",
                "sub_queries": [
                    {"type": "rag_query", "query": "支付回调处理"},
                    {
                        "type": "rag_graph",
                        "query_type": "business_flow",
                        "name": "支付",
                    },
                ],
            },
            {
                "sufficient": True,
                "analysis": "支付回调失败会影响订单状态更新和退款流程。",
                "business_flows": [
                    {"name": "订单支付", "impact": "订单状态无法更新为已支付"}
                ],
                "code_locations": [
                    {"file": "payment/callback.py", "function": "handle_callback"}
                ],
            },
        ]
    )
    return llm


@pytest.fixture
def mock_hybrid():
    from query.hybrid_query import HybridQueryService

    svc = MagicMock(spec=HybridQueryService)
    m = [{"name": "handle_callback", "file": "payment/callback.py"}]
    svc.search_with_context = AsyncMock(
        return_value={
            "results": m,
            "semantic_matches": m,
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "支付回调",
            "confidence": 0.0,
            "no_results_reason": "",
        }
    )
    return svc


@pytest.fixture
def mock_graph():
    from query.graph_query import GraphQueryService, QueryResult

    svc = MagicMock(spec=GraphQueryService)
    svc.find_business_flow = AsyncMock(
        return_value=QueryResult(data=[], query="", params={})
    )
    svc.find_flows_for_function = AsyncMock(
        return_value=QueryResult(data=[], query="", params={})
    )
    svc.find_related_concepts = AsyncMock(
        return_value=QueryResult(data=[], query="", params={})
    )
    return svc


class TestDeepSearchEngine:
    @pytest.mark.asyncio
    async def test_deep_search_returns_analysis(
        self, mock_llm, mock_hybrid, mock_graph
    ):
        from query.deep_search import DeepSearchEngine

        engine = DeepSearchEngine(
            llm=mock_llm, hybrid_svc=mock_hybrid, graph_svc=mock_graph
        )
        result = await engine.search("支付回调失败可能影响哪些业务？")
        assert "analysis" in result
        assert "search_trace" in result
        assert result["analysis"] == "支付回调失败会影响订单状态更新和退款流程。"
        assert len(result["business_flows"]) == 1
        assert len(result["code_locations"]) == 1

    @pytest.mark.asyncio
    async def test_deep_search_handles_plan_failure(
        self, mock_hybrid, mock_graph
    ):
        from llm.provider import LLMProvider
        from query.deep_search import DeepSearchEngine

        failing_llm = MagicMock(spec=LLMProvider)
        failing_llm.complete_json = AsyncMock(
            side_effect=[
                Exception("LLM plan failed"),
                {
                    "sufficient": True,
                    "analysis": "Fallback result",
                    "business_flows": [],
                    "code_locations": [],
                },
            ]
        )
        engine = DeepSearchEngine(
            llm=failing_llm, hybrid_svc=mock_hybrid, graph_svc=mock_graph
        )
        result = await engine.search("test query")
        assert "search_trace" in result
        assert result["analysis"] == "Fallback result"

    @pytest.mark.asyncio
    async def test_deep_search_max_iterations(
        self, mock_hybrid, mock_graph
    ):
        from llm.provider import LLMProvider
        from query.deep_search import DeepSearchEngine

        llm = MagicMock(spec=LLMProvider)
        llm.complete_json = AsyncMock(
            side_effect=[
                {
                    "intent": "search",
                    "sub_queries": [{"type": "rag_query", "query": "test"}],
                },
                {
                    "sufficient": False,
                    "analysis": "Need more info",
                    "business_flows": [],
                    "code_locations": [],
                    "follow_up_queries": [
                        {"type": "rag_query", "query": "more test"}
                    ],
                },
                {
                    "sufficient": True,
                    "analysis": "Complete",
                    "business_flows": [],
                    "code_locations": [],
                },
            ]
        )
        engine = DeepSearchEngine(
            llm=llm, hybrid_svc=mock_hybrid, graph_svc=mock_graph
        )
        result = await engine.search("test", max_iterations=2)
        assert result["analysis"] == "Complete"
        assert len(result["search_trace"]) >= 4

    @pytest.mark.asyncio
    async def test_execute_single_rag_graph(self, mock_llm, mock_hybrid, mock_graph):
        from query.deep_search import DeepSearchEngine

        engine = DeepSearchEngine(
            llm=mock_llm, hybrid_svc=mock_hybrid, graph_svc=mock_graph
        )
        result = await engine._execute_single(
            {"type": "rag_graph", "query_type": "business_flow", "name": "支付"}
        )
        assert result is not None
        assert result["type"] == "graph"

    @pytest.mark.asyncio
    async def test_execute_single_unknown_type(self, mock_llm, mock_hybrid, mock_graph):
        from query.deep_search import DeepSearchEngine

        engine = DeepSearchEngine(
            llm=mock_llm, hybrid_svc=mock_hybrid, graph_svc=mock_graph
        )
        result = await engine._execute_single({"type": "unknown"})
        assert result is None
