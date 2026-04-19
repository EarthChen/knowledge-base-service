"""Tests for the deep search SSE streaming endpoint and search_stream method."""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestDeepSearchStream:
    """Unit tests for DeepSearchEngine.search_stream."""

    @pytest.mark.asyncio
    async def test_stream_yields_plan_first(self):
        from query.deep_search import DeepSearchEngine

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "intent": "search",
            "sub_queries": [{"type": "rag_query", "query": "test"}],
        })
        mock_hybrid = AsyncMock()
        mock_hybrid.search_with_context = AsyncMock(return_value={
            "results": [{"name": "foo", "score": 0.9}],
            "semantic_matches": [{"name": "foo", "score": 0.9}],
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.0,
            "no_results_reason": "",
        })
        mock_graph = AsyncMock()

        engine = DeepSearchEngine(mock_llm, mock_hybrid, mock_graph)

        # Override _synthesize to return sufficient=True immediately
        engine._synthesize = AsyncMock(return_value={
            "sufficient": True,
            "analysis": "Test analysis",
            "business_flows": [],
            "code_locations": [],
        })

        events = []
        async for event in engine.search_stream("test query"):
            events.append(event)

        assert events[0]["type"] == "plan"
        assert "sub_queries" in events[0]["data"]

    @pytest.mark.asyncio
    async def test_stream_ends_with_conclusion(self):
        from query.deep_search import DeepSearchEngine

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "intent": "search",
            "sub_queries": [{"type": "rag_query", "query": "test"}],
        })
        mock_hybrid = AsyncMock()
        mock_hybrid.search_with_context = AsyncMock(return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.0,
            "no_results_reason": "",
        })
        mock_graph = AsyncMock()

        engine = DeepSearchEngine(mock_llm, mock_hybrid, mock_graph)
        engine._synthesize = AsyncMock(return_value={
            "sufficient": True,
            "analysis": "Done",
            "business_flows": [],
            "code_locations": [],
        })

        events = []
        async for event in engine.search_stream("q"):
            events.append(event)

        assert events[-1]["type"] == "conclusion"
        assert "analysis" in events[-1]["data"]

    @pytest.mark.asyncio
    async def test_stream_event_order(self):
        from query.deep_search import DeepSearchEngine

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "intent": "search",
            "sub_queries": [{"type": "rag_query", "query": "test"}],
        })
        mock_hybrid = AsyncMock()
        mock_hybrid.search_with_context = AsyncMock(return_value={
            "results": [{"name": "a"}],
            "semantic_matches": [{"name": "a"}],
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.0,
            "no_results_reason": "",
        })
        mock_graph = AsyncMock()

        engine = DeepSearchEngine(mock_llm, mock_hybrid, mock_graph)
        engine._synthesize = AsyncMock(return_value={
            "sufficient": True,
            "analysis": "OK",
            "business_flows": [],
            "code_locations": [],
        })

        types = []
        async for event in engine.search_stream("q"):
            types.append(event["type"])

        assert types[0] == "plan"
        assert "progress" in types
        assert "search_done" in types
        assert "synthesis" in types
        assert types[-1] == "conclusion"

    @pytest.mark.asyncio
    async def test_stream_plan_failure_yields_error(self):
        from query.deep_search import DeepSearchEngine

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM down"))
        mock_hybrid = AsyncMock()
        mock_graph = AsyncMock()

        engine = DeepSearchEngine(mock_llm, mock_hybrid, mock_graph)
        # Also make _plan_search raise
        engine._plan_search = AsyncMock(side_effect=RuntimeError("LLM down"))

        events = []
        async for event in engine.search_stream("q"):
            events.append(event)

        assert events[0]["type"] == "error"
        assert events[0]["data"]["phase"] == "plan"
        # Should terminate immediately
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_stream_sufficient_false_continues(self):
        from query.deep_search import DeepSearchEngine

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "intent": "search",
            "sub_queries": [{"type": "rag_query", "query": "test"}],
        })
        mock_hybrid = AsyncMock()
        mock_hybrid.search_with_context = AsyncMock(return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.0,
            "no_results_reason": "",
        })
        mock_graph = AsyncMock()

        call_count = 0

        async def mock_synthesize(query, results, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "sufficient": False,
                    "analysis": "Partial",
                    "follow_up_queries": [{"type": "rag_query", "query": "more"}],
                    "business_flows": [],
                    "code_locations": [],
                }
            return {
                "sufficient": True,
                "analysis": "Complete",
                "business_flows": [],
                "code_locations": [],
            }

        engine = DeepSearchEngine(mock_llm, mock_hybrid, mock_graph)
        engine._synthesize = mock_synthesize

        types = []
        async for event in engine.search_stream("q", max_iterations=3):
            types.append(event["type"])

        # Should have 2 rounds of search
        assert types.count("progress") == 2
        assert types.count("synthesis") == 2
        assert types[-1] == "conclusion"

    @pytest.mark.asyncio
    async def test_stream_max_iterations_respected(self):
        from query.deep_search import DeepSearchEngine

        mock_llm = AsyncMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "intent": "search",
            "sub_queries": [{"type": "rag_query", "query": "test"}],
        })
        mock_hybrid = AsyncMock()
        mock_hybrid.search_with_context = AsyncMock(return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.0,
            "no_results_reason": "",
        })
        mock_graph = AsyncMock()

        engine = DeepSearchEngine(mock_llm, mock_hybrid, mock_graph)
        engine._synthesize = AsyncMock(return_value={
            "sufficient": False,
            "analysis": "Not done",
            "follow_up_queries": [{"type": "rag_query", "query": "more"}],
            "business_flows": [],
            "code_locations": [],
        })

        types = []
        async for event in engine.search_stream("q", max_iterations=2):
            types.append(event["type"])

        assert types.count("progress") == 2
        assert types[-1] == "conclusion"
