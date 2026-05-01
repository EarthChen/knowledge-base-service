from __future__ import annotations

import pytest
from wiki.rag.protocol import RetrievalScope

from query.deep_search import DeepSearchEngine


class _FakeRAGEngine:
    def __init__(self) -> None:
        self.called = False
        self.last_scope: RetrievalScope | None = None

    async def arun(self, *, question, scope, max_rounds=7):
        self.called = True
        self.last_scope = scope
        return {
            "current_draft": "deep search answer",
            "is_complete": True,
            "confidence": 0.92,
            "accumulated_context": [],
            "sse_events": [
                {"type": "searching", "queries": [question]},
                {
                    "type": "done",
                    "final_answer": "deep search answer",
                    "total_rounds": 2,
                    "confidence": 0.92,
                },
            ],
            "round": 2,
        }


@pytest.mark.asyncio
async def test_deep_search_with_rag_engine():
    """DeepSearchEngine delegates to the injected RAG engine."""
    engine = _FakeRAGEngine()
    ds = DeepSearchEngine(rag_engine=engine)
    result = await ds.search("test question", business_id="biz-1")
    assert engine.called
    assert result["analysis"] == "deep search answer"
    assert engine.last_scope is not None
    assert engine.last_scope.scope_type == "business"
    assert engine.last_scope.business_id == "biz-1"
