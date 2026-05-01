from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.deep_research import DeepResearchService


@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(
        return_value={
            "current_draft": "Sub-answer for the question.",
            "accumulated_context": [],
            "sse_events": [],
            "round": 1,
            "confidence": 0.9,
        },
    )
    return engine


@pytest.mark.asyncio
async def test_research_delegates_to_engine(mock_engine):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="sub q1\nsub q2")
    svc = DeepResearchService(rag_engine=mock_engine, llm=llm)
    result = await svc.research(question="Compare auth methods", business_id="biz-1")
    assert mock_engine.arun.call_count >= 1
    assert "synthesis" in result or "sub_answers" in result
