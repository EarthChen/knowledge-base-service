"""Tests for IterativeRAGEngine.arun_stream and batch arun compatibility."""

from __future__ import annotations

import pytest

from wiki.rag.engine import IterativeRAGEngine
from wiki.rag.protocol import Chunk, RetrievalScope


class _MemRetriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks

    async def retrieve(self, queries, scope, *, limit=10, exclude_ids=None):
        return self._chunks[:limit]


class _CompleteFirstRoundLLM:
    async def complete(self, messages, **kwargs):
        return (
            '{"answer":"streamed answer text","gaps":[],"next_queries":[],'
            '"confidence":0.92,"is_complete":true}'
        )


def _collect_stream_events(engine: IterativeRAGEngine, *, question: str = "q?", max_rounds: int = 3):
    async def _run():
        out: list[dict] = []
        async for ev in engine.arun_stream(
            question=question,
            scope=RetrievalScope(scope_type="global"),
            max_rounds=max_rounds,
        ):
            out.append(ev)
        return out

    return _run


@pytest.mark.asyncio
async def test_arun_stream_yields_searching_sse_before_done() -> None:
    chunks = [Chunk(content="ctx", source="s", title="T", relevance=0.9)]
    engine = IterativeRAGEngine(retriever=_MemRetriever(chunks), llm=_CompleteFirstRoundLLM())

    events = await _collect_stream_events(engine)()

    sse_payloads = [e for e in events if e.get("type") == "sse"]
    assert sse_payloads, "expected at least one sse chunk"
    types_seen = [e["data"]["type"] for e in sse_payloads]
    assert "searching" in types_seen, f"missing searching in {types_seen}"


@pytest.mark.asyncio
async def test_arun_stream_yields_draft_content() -> None:
    chunks = [Chunk(content="ctx", source="s", title="T", relevance=0.9)]
    engine = IterativeRAGEngine(retriever=_MemRetriever(chunks), llm=_CompleteFirstRoundLLM())

    events = await _collect_stream_events(engine)()

    drafts = [e for e in events if e.get("type") == "draft"]
    assert drafts, "expected draft events"
    assert any("streamed answer text" in str(d.get("content", "")) for d in drafts)

    done = [e for e in events if e.get("type") == "done"]
    assert len(done) == 1
    assert float(done[0]["confidence"]) >= 0.85
    assert isinstance(done[0].get("accumulated_context"), list)


@pytest.mark.asyncio
async def test_arun_batch_mode_unchanged() -> None:
    chunks = [Chunk(content="ctx", source="s", title="T", relevance=0.9)]
    engine = IterativeRAGEngine(retriever=_MemRetriever(chunks), llm=_CompleteFirstRoundLLM())

    state = await engine.arun(
        question="batch question",
        scope=RetrievalScope(scope_type="global"),
        max_rounds=3,
    )

    assert state["is_complete"] is True
    assert state["current_draft"] == "streamed answer text"
    assert state["confidence"] >= 0.85
    assert any(e.get("type") == "searching" for e in state.get("sse_events", []))
