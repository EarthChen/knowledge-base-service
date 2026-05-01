from __future__ import annotations

import pytest
from wiki.ask import WikiAskService
from wiki.search import SearchResponse, SearchResult


class _FakeSearch:
    async def search(self, repository, query, mode="hybrid", limit=10, min_score=0.0, *, scope=None):
        return SearchResponse(
            query_expansion=None,
            results=[
                SearchResult(
                    page_path="/p1",
                    title="t1",
                    score=0.9,
                    snippet="s1",
                    source_locations=[],
                    context={},
                ),
            ],
            total=1,
        )


class _FakeLLM:
    async def complete(self, messages, **kwargs):
        return "answer from LLM"


class _FakeRAGEngine:
    """Fake IterativeRAGEngine that returns a canned RAGState."""

    def __init__(self):
        self.called = False

    async def arun(self, *, question, scope, max_rounds=7):
        self.called = True
        return {
            "current_draft": "iterative answer",
            "is_complete": True,
            "confidence": 0.95,
            "accumulated_context": [],
            "sse_events": [
                {"type": "searching", "queries": [question]},
                {"type": "draft", "round": 1, "content": "iterative answer", "confidence": 0.95},
                {"type": "done", "final_answer": "iterative answer", "total_rounds": 1, "confidence": 0.95},
            ],
            "round": 1,
        }


@pytest.mark.asyncio
async def test_ask_uses_iterative_rag_when_engine_set():
    engine = _FakeRAGEngine()
    svc = WikiAskService(
        search=_FakeSearch(),
        llm=_FakeLLM(),
        rag_engine=engine,
        use_iterative_rag=True,
    )
    events = []
    async for ev in svc.ask_stream(repository="repo", question="what?"):
        events.append(ev)
    assert engine.called
    event_types = [e["event"] for e in events]
    assert "wiki-answer" in event_types
    assert "wiki-answer-complete" in event_types


@pytest.mark.asyncio
async def test_ask_falls_back_to_legacy_when_no_engine():
    svc = WikiAskService(
        search=_FakeSearch(),
        llm=_FakeLLM(),
    )
    events = []
    async for ev in svc.ask_stream(repository="repo", question="what?"):
        events.append(ev)
    event_types = [e["event"] for e in events]
    assert "wiki-answer" in event_types
