from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.ask import WikiAskService
from wiki.rag.protocol import Chunk


@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.arun = AsyncMock(
        return_value={
            "current_draft": "The answer is 42.",
            "accumulated_context": [
                Chunk(
                    content="guide content",
                    source="wiki",
                    title="guide.md",
                    relevance=0.9,
                    metadata={"page_path": "guide.md"},
                ),
            ],
            "sse_events": [
                {"type": "searching", "round": 1},
                {"type": "draft", "round": 1, "content": "The answer is 42."},
                {"type": "done", "final_answer": "The answer is 42."},
            ],
            "round": 1,
            "confidence": 0.95,
        }
    )
    return engine


@pytest.mark.asyncio
async def test_ask_stream_uses_engine(mock_engine):
    svc = WikiAskService(
        search=AsyncMock(),
        llm=MagicMock(),
        rag_engine=mock_engine,
    )
    events = []
    async for event in svc.ask_stream("repo-1", "What is 42?", business_id="biz-1"):
        events.append(event)

    mock_engine.arun.assert_called_once()
    call_kw = mock_engine.arun.call_args.kwargs
    assert call_kw.get("question") == "What is 42?"
    assert call_kw.get("max_rounds") == 5
    scope = call_kw.get("scope")
    assert scope is not None
    assert scope.scope_type == "business"
    assert scope.business_id == "biz-1"
    assert scope.repository == "repo-1"

    event_types = [e.get("type") or e.get("event") for e in events]
    assert any("wiki-answer" in str(t) for t in event_types)
