from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_rag_engine():
    engine = MagicMock()
    engine.arun = AsyncMock(
        return_value={
            "current_draft": "支付回调失败会影响订单状态更新和退款流程。",
            "sse_events": [
                {"type": "searching", "round": 1},
                {"type": "done", "final_answer": " done"},
            ],
            "round": 2,
            "confidence": 0.9,
        }
    )
    return engine


class TestDeepSearchEngine:
    @pytest.mark.asyncio
    async def test_deep_search_returns_analysis(self, mock_rag_engine):
        from query.deep_search import DeepSearchEngine

        engine = DeepSearchEngine(rag_engine=mock_rag_engine)
        result = await engine.search("支付回调失败可能影响哪些业务？")
        assert "analysis" in result
        assert "search_trace" in result
        assert result["analysis"] == "支付回调失败会影响订单状态更新和退款流程。"
        assert result["business_flows"] == []
        assert result["code_locations"] == []
        assert len(result["search_trace"]) == 2
        assert result["search_trace"][0]["stage"] == "searching"

    @pytest.mark.asyncio
    async def test_deep_search_handles_arun_failure(self, mock_rag_engine):
        from query.deep_search import DeepSearchEngine

        mock_rag_engine.arun = AsyncMock(side_effect=RuntimeError("RAG down"))

        engine = DeepSearchEngine(rag_engine=mock_rag_engine)
        result = await engine.search("test query")
        assert result["analysis"] == ""
        assert result["search_trace"] == []

    @pytest.mark.asyncio
    async def test_deep_search_max_iterations_passed_to_arun(self, mock_rag_engine):
        from query.deep_search import DeepSearchEngine

        engine = DeepSearchEngine(rag_engine=mock_rag_engine)
        await engine.search("test", max_iterations=2)
        mock_rag_engine.arun.assert_awaited_once()
        _call = mock_rag_engine.arun.call_args
        assert _call.kwargs["max_rounds"] == 2

    @pytest.mark.asyncio
    async def test_tenant_id_maps_to_business_scope(self, mock_rag_engine):
        from query.deep_search import DeepSearchEngine

        engine = DeepSearchEngine(rag_engine=mock_rag_engine)
        await engine.search("q", tenant_id="tenant-9")
        scope = mock_rag_engine.arun.call_args.kwargs["scope"]
        assert scope.scope_type == "business"
        assert scope.business_id == "tenant-9"
