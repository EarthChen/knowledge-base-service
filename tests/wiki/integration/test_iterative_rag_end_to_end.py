"""Integration test: Protocol → Retriever → Engine → Events end-to-end."""

from __future__ import annotations

import pytest

from wiki.rag.composite_retriever import CompositeRetriever
from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.events import rag_sse_append, sse_thinking_start
from wiki.rag.protocol import Chunk, RetrievalScope


class _MemRetriever:
    def __init__(self, chunks: list[Chunk]):
        self._chunks = chunks

    async def retrieve(self, queries, scope, *, limit=10, exclude_ids=None):
        return self._chunks[:limit]


class _ControlledLLM:
    """LLM that returns a JSON response indicating completion after first round."""

    def __init__(self):
        self.call_count = 0

    async def complete(self, messages, **kwargs):
        self.call_count += 1
        return '{"answer":"integrated answer","gaps":[],"next_queries":[],"confidence":0.92,"is_complete":true}'


@pytest.mark.asyncio
async def test_full_pipeline_integration():
    """Verify CompositeRetriever + IterativeRAGEngine produces expected output."""
    wiki_chunks = [
        Chunk(content="wiki content A", source="wiki:/a", title="Page A", relevance=0.9),
        Chunk(content="wiki content B", source="wiki:/b", title="Page B", relevance=0.7),
    ]
    code_chunks = [
        Chunk(content="def foo(): pass", source="code:repo/foo.py", title="foo", relevance=0.8),
    ]

    wiki_ret = _MemRetriever(wiki_chunks)
    code_ret = _MemRetriever(code_chunks)
    composite = CompositeRetriever(children=[wiki_ret, code_ret])

    llm = _ControlledLLM()
    engine = IterativeRAGEngine(
        retriever=composite,
        plan_llm=llm,
        generate_llm=llm,
    )

    state = await engine.arun(
        question="How does foo work?",
        scope=RetrievalScope(scope_type="global"),
        max_rounds=3,
    )

    assert state["is_complete"] is True
    assert state["current_draft"] == "integrated answer"
    assert state["confidence"] >= 0.85
    assert llm.call_count >= 1
    assert len(state.get("sse_events", [])) >= 2  # at least searching + draft


@pytest.mark.asyncio
async def test_multi_round_integration():
    """Engine should perform multiple rounds when LLM reports gaps."""
    chunks = [Chunk(content="ctx", source="s", title="t", relevance=0.9)]
    retriever = _MemRetriever(chunks)

    class _MultiRoundLLM:
        def __init__(self):
            self.call_count = 0

        async def complete(self, messages, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return (
                    '{"answer":"partial","gaps":["missing X"],'
                    '"next_queries":["what is X?"],"confidence":0.5,"is_complete":false}'
                )
            return '{"answer":"complete answer","gaps":[],"next_queries":[],"confidence":0.95,"is_complete":true}'

    llm = _MultiRoundLLM()
    engine = IterativeRAGEngine(
        retriever=retriever,
        plan_llm=llm,
        generate_llm=llm,
    )

    state = await engine.arun(
        question="Complex question",
        scope=RetrievalScope(scope_type="global"),
        max_rounds=5,
    )

    assert state["is_complete"] is True
    assert llm.call_count >= 2
    assert state["current_draft"] == "complete answer"


@pytest.mark.asyncio
async def test_sse_events_shape():
    """SSE events should have consistent shape throughout pipeline."""
    ev = sse_thinking_start(round_no=1, max_rounds=5)
    assert ev["type"] == "thinking_start"
    assert ev["round"] == 1

    base = {"sse_events": []}
    result = rag_sse_append(base, "searching", {"queries": ["q1"]})
    assert len(result) == 1
    assert result[0]["type"] == "searching"
    assert result[0]["queries"] == ["q1"]


@pytest.mark.asyncio
async def test_composite_retriever_merges_sources():
    """CompositeRetriever should merge and sort by relevance."""
    r1 = _MemRetriever([Chunk(content="a", source="s1", title="t1", relevance=0.5)])
    r2 = _MemRetriever([Chunk(content="b", source="s2", title="t2", relevance=0.9)])

    composite = CompositeRetriever(children=[r1, r2])
    chunks = await composite.retrieve(
        ["query"], RetrievalScope(scope_type="global"), limit=10
    )

    assert len(chunks) == 2
    assert chunks[0].relevance >= chunks[1].relevance  # sorted by relevance desc
