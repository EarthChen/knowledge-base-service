from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.protocol import Chunk, RetrievalScope


@pytest.fixture
def mock_retriever():
    r = AsyncMock()
    r.retrieve = AsyncMock(
        return_value=[
            Chunk(content="some context", source="wiki", title="Page 1", relevance=0.8),
        ]
    )
    return r


@pytest.mark.asyncio
async def test_simple_question_skips_plan_and_evaluate(mock_retriever):
    """High-confidence answer on Round 1 should not trigger plan or evaluate."""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=(
            '{"answer":"simple answer","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'
        )
    )

    engine = IterativeRAGEngine(retriever=mock_retriever, llm=llm)
    scope = RetrievalScope(scope_type="global")
    state = await engine.arun(question="what is X?", scope=scope, max_rounds=5)

    assert state.get("round", 0) == 1
    event_types = [e.get("type") for e in state.get("sse_events", [])]
    assert "planning" not in event_types
    assert "evaluating" not in event_types


@pytest.mark.asyncio
async def test_plan_node_activates_on_round_2(mock_retriever):
    """Plan node should activate when round >= 2."""
    call_count = {"n": 0}

    async def multi_round(messages, **kwargs):
        call_count["n"] += 1
        content = messages[0]["content"] if messages else ""
        if "sub-queries" in content.lower() or "decompose" in content.lower():
            return '{"sub_queries": ["refined query"]}'
        if call_count["n"] >= 3:
            return '{"answer":"final","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'
        return (
            '{"answer":"partial","gaps":["gap"],"next_queries":["follow up"],'
            '"confidence":0.6,"is_complete":false}'
        )

    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=multi_round)

    engine = IterativeRAGEngine(retriever=mock_retriever, llm=llm)
    scope = RetrievalScope(scope_type="global")
    state = await engine.arun(question="complex", scope=scope, max_rounds=5)

    event_types = [e.get("type") for e in state.get("sse_events", [])]
    assert "planning" in event_types
