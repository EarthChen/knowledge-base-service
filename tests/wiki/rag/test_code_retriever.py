from __future__ import annotations

import pytest

from wiki.rag.code_retriever import CodeRetriever
from wiki.rag.protocol import RetrievalScope


class _HybridStub:
    async def search_with_context(self, *args, **kwargs):
        return {
            "results": [
                {"name": "fn", "file": "a.py", "type": "Function", "rrf_score": 0.82, "summary": "does work"}
            ],
            "total": 1,
        }


@pytest.mark.asyncio
async def test_code_retriever_merges_query_list():
    h = _HybridStub()
    r = CodeRetriever(h)
    scope = RetrievalScope(scope_type="global")
    chunks = await r.retrieve(["login"], scope, limit=5)
    assert len(chunks) == 1
    assert chunks[0].title == "fn"
    assert "code:" in chunks[0].source
