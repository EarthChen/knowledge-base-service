from __future__ import annotations

import pytest

from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.protocol import Chunk, RetrievalScope


class _FixedRetriever:
    async def retrieve(self, queries, scope, *, limit=10, exclude_ids=None):
        return [Chunk(content="ctx", source="wiki:/x", title="t", relevance=0.9, metadata={})]


class _EchoLLM:
    async def complete(self, messages, **kwargs):
        return '{"answer":"ok","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'


@pytest.mark.asyncio
async def test_engine_runs_single_round_and_completes():
    engine = IterativeRAGEngine(
        retriever=_FixedRetriever(),
        llm=_EchoLLM(),
    )
    state = await engine.arun(question="what?", scope=RetrievalScope(scope_type="global"), max_rounds=3)
    assert state["is_complete"] is True
    assert state["current_draft"]
