from __future__ import annotations

import pytest
from wiki.deep_research import DeepResearchService


class _FakeLLM:
    async def complete(self, messages, **kwargs):
        return "sub1?\nsub2?"


class _FakeAsk:
    async def ask_stream(self, repository, question, scope=None, business_id=None):
        yield {"event": "wiki-answer", "data": {"content": "answer"}}


class _FakeRAGEngine:
    def __init__(self):
        self.call_count = 0

    async def arun(self, *, question, scope, max_rounds=7):
        self.call_count += 1
        return {
            "current_draft": f"rag answer for: {question}",
            "is_complete": True,
            "confidence": 0.9,
            "round": 1,
        }


@pytest.mark.asyncio
async def test_research_with_rag_engine():
    engine = _FakeRAGEngine()
    svc = DeepResearchService(
        ask_service=_FakeAsk(),
        llm=_FakeLLM(),
        rag_engine=engine,
        use_iterative_rag=True,
    )
    result = await svc.research("complex question", "repo", "biz-1")
    assert engine.call_count > 0
    assert "synthesis" in result


@pytest.mark.asyncio
async def test_research_legacy_without_engine():
    svc = DeepResearchService(
        ask_service=_FakeAsk(),
        llm=_FakeLLM(),
    )
    result = await svc.research("complex question", "repo", "biz-1")
    assert "question" in result
