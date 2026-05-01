"""Tests for the deep search SSE streaming endpoint and search_stream method."""

import pytest
from unittest.mock import AsyncMock, MagicMock


def _mock_rag_state(analysis: str = "Test analysis"):
    return {
        "current_draft": analysis,
        "sse_events": [
            {"type": "searching", "round": 1},
            {"type": "draft", "content": "partial"},
        ],
        "round": 1,
        "confidence": 0.9,
    }


class TestDeepSearchStream:
    """Unit tests for DeepSearchEngine.search_stream."""

    @pytest.mark.asyncio
    async def test_stream_yields_plan_first(self):
        from query.deep_search import DeepSearchEngine

        mock_rag = MagicMock()
        mock_rag.arun = AsyncMock(return_value=_mock_rag_state())

        engine = DeepSearchEngine(rag_engine=mock_rag)

        events = []
        async for event in engine.search_stream("test query"):
            events.append(event)

        assert events[0]["type"] == "plan"
        assert events[0]["data"]["intent"] == "test query"
        assert events[0]["data"]["sub_queries"] == ["test query"]

    @pytest.mark.asyncio
    async def test_stream_ends_with_conclusion(self):
        from query.deep_search import DeepSearchEngine

        mock_rag = MagicMock()
        mock_rag.arun = AsyncMock(return_value=_mock_rag_state("Done"))

        engine = DeepSearchEngine(rag_engine=mock_rag)

        events = []
        async for event in engine.search_stream("q"):
            events.append(event)

        assert events[-1]["type"] == "conclusion"
        assert events[-1]["data"]["analysis"] == "Done"
        assert events[-1]["data"]["sufficient"] is True

    @pytest.mark.asyncio
    async def test_stream_event_order(self):
        from query.deep_search import DeepSearchEngine

        mock_rag = MagicMock()
        mock_rag.arun = AsyncMock(return_value=_mock_rag_state("OK"))

        engine = DeepSearchEngine(rag_engine=mock_rag)

        types = []
        async for event in engine.search_stream("q"):
            types.append(event["type"])

        assert types[0] == "plan"
        assert types.count("progress") == 2
        assert types[-1] == "conclusion"

    @pytest.mark.asyncio
    async def test_stream_arun_failure_after_plan(self):
        from query.deep_search import DeepSearchEngine

        mock_rag = MagicMock()
        mock_rag.arun = AsyncMock(side_effect=RuntimeError("RAG down"))

        engine = DeepSearchEngine(rag_engine=mock_rag)

        events = []
        async for event in engine.search_stream("q"):
            events.append(event)

        assert len(events) == 2
        assert events[0]["type"] == "plan"
        assert events[1]["type"] == "conclusion"
        assert events[1]["data"]["sufficient"] is False

    @pytest.mark.asyncio
    async def test_single_arun_call_covers_follow_up_rounds(self):
        from query.deep_search import DeepSearchEngine

        mock_rag = MagicMock()
        mock_rag.arun = AsyncMock(
            return_value={
                "current_draft": "Complete",
                "sse_events": [
                    {"type": "searching"},
                    {"type": "refining"},
                    {"type": "searching"},
                    {"type": "done"},
                ],
            }
        )

        engine = DeepSearchEngine(rag_engine=mock_rag)

        types = []
        async for event in engine.search_stream("q", max_iterations=3):
            types.append(event["type"])

        mock_rag.arun.assert_awaited_once()
        assert types.count("progress") == 4
        assert types[-1] == "conclusion"

    @pytest.mark.asyncio
    async def test_stream_max_iterations_passed_to_arun(self):
        from query.deep_search import DeepSearchEngine

        mock_rag = MagicMock()
        mock_rag.arun = AsyncMock(return_value=_mock_rag_state("x"))

        engine = DeepSearchEngine(rag_engine=mock_rag)

        async for _ in engine.search_stream("q", max_iterations=2):
            pass

        assert mock_rag.arun.call_args.kwargs["max_rounds"] == 2
