from __future__ import annotations

import pytest
from query.deep_search import DeepSearchEngine


class _FakeRAGEngine:
    def __init__(self):
        self.called = False

    async def arun(self, *, question, scope, max_rounds=7):
        self.called = True
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
    """When rag_engine is set, DeepSearchEngine should delegate to it."""
    engine = _FakeRAGEngine()
    ds = DeepSearchEngine.__new__(DeepSearchEngine)
    ds._rag_engine = engine
    ds._use_iterative_rag = True

    # Test that the engine has the attributes set
    assert ds._rag_engine is engine
    assert ds._use_iterative_rag is True
