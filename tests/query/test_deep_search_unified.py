from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from query.deep_search import DeepSearchEngine


@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(
        return_value={
            "current_draft": "Analysis: the system uses microservices.",
            "accumulated_context": [],
            "sse_events": [
                {"type": "searching", "round": 1},
                {"type": "done", "final_answer": "Analysis complete."},
            ],
            "round": 2,
            "confidence": 0.88,
        }
    )
    return engine


@pytest.mark.asyncio
async def test_deep_search_delegates_to_engine(mock_engine):
    ds = DeepSearchEngine(rag_engine=mock_engine)
    result = await ds.search(
        query="How does the system work?",
        business_id="biz-1",
    )
    mock_engine.arun.assert_called_once()
    assert "microservices" in result["analysis"]


@pytest.mark.asyncio
async def test_deep_search_stream_yields_events(mock_engine):
    ds = DeepSearchEngine(rag_engine=mock_engine)
    events = []
    async for event in ds.search_stream(
        query="How does auth work?",
        business_id="biz-1",
    ):
        events.append(event)
    assert len(events) > 0
