from __future__ import annotations

import pytest

from wiki.deep_research import DeepResearchService


class _FakeLLM:
    async def complete(self, messages, **kwargs):
        return "sub1?\nsub2?"


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
        rag_engine=engine,
        llm=_FakeLLM(),
    )
    result = await svc.research("complex question", repository="repo", business_id="biz-1")
    assert engine.call_count > 0
    assert "synthesis" in result
    assert isinstance(result["sub_questions"], list)
    assert result["sub_answers"]
