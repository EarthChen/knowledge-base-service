from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wiki.rag.engine import IterativeRAGEngine, RAGState, _build_init_state
from wiki.rag.protocol import Chunk, RetrievalScope


class _FixedRetriever:
    async def retrieve(self, queries, scope, *, limit=10, exclude_ids=None):
        return [Chunk(content="ctx", source="wiki:/x", title="t", relevance=0.9, metadata={})]


@pytest.fixture
def mock_retriever():
    r = AsyncMock()
    r.retrieve = AsyncMock(
        return_value=[
            Chunk(content="some context", source="wiki", title="Page 1", relevance=0.8),
        ]
    )
    return r


def test_rag_state_and_init_include_eval_suggestions():
    init = _build_init_state(
        question="q",
        scope=RetrievalScope(scope_type="global"),
        max_rounds=5,
    )
    assert init.get("eval_suggestions") == []

    extra: RAGState = {**init, "eval_suggestions": ["fix citation", "add examples"]}
    assert extra["eval_suggestions"] == ["fix citation", "add examples"]


@pytest.mark.asyncio
async def test_plan_prompt_includes_eval_suggestions_after_evaluate(mock_retriever):
    """After evaluate runs, the next plan call's prompt must list prior suggestions."""
    call_count = {"n": 0}
    plan_prompts: list[str] = []

    async def side_effect(messages, **kwargs):
        call_count["n"] += 1
        content = messages[0]["content"] if messages else ""

        if "Evaluate this answer independently" in content:
            return (
                '{"score": 0.5, "suggestions": ["Be more specific about dates"], '
                '"next_queries": ["when did X happen"]}'
            )

        if "Decompose into 2-4 precise sub-queries" in content:
            plan_prompts.append(content)
            return '{"sub_queries": ["refined from plan"]}'

        n = call_count["n"]
        if n >= 8:
            return '{"answer":"final","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'
        return (
            '{"answer":"partial","gaps":["gap"],"next_queries":["follow up"],'
            '"confidence":0.6,"is_complete":false}'
        )

    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=side_effect)

    engine = IterativeRAGEngine(retriever=mock_retriever, llm=llm)
    scope = RetrievalScope(scope_type="global")
    await engine.arun(question="complex topic", scope=scope, max_rounds=7)

    assert plan_prompts, "expected at least one plan call"
    feedback_blocks = [p for p in plan_prompts if "Previous evaluation feedback:" in p]
    assert feedback_blocks, "expected a plan prompt after evaluate to include feedback"
    assert any("Be more specific about dates" in p for p in feedback_blocks)


@pytest.mark.asyncio
async def test_arun_batch_mode_still_completes():
    """Single-round high-confidence path still completes (no regression)."""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=(
            '{"answer":"ok","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'
        )
    )

    engine = IterativeRAGEngine(retriever=_FixedRetriever(), llm=llm)
    state = await engine.arun(
        question="what?",
        scope=RetrievalScope(scope_type="global"),
        max_rounds=3,
    )
    assert state["is_complete"] is True
    assert state["current_draft"]
    assert state.get("eval_suggestions") == []
