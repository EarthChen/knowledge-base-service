from __future__ import annotations

import pytest

from wiki.rag.composite_retriever import CompositeRetriever
from wiki.rag.protocol import Chunk, RetrievalScope


class _MemRetriever:
    def __init__(self, tag: str, score: float):
        self.tag = tag
        self.score = score

    async def retrieve(self, queries, scope, *, limit=10, exclude_ids=None):
        return [Chunk(content=self.tag, source=f"{self.tag}:x", title=self.tag, relevance=self.score, metadata={})]


@pytest.mark.asyncio
async def test_composite_merges_and_sorts_by_relevance():
    a = _MemRetriever("wiki", 0.5)
    b = _MemRetriever("code", 0.9)
    c = CompositeRetriever([a, b])
    chunks = await c.retrieve(["q"], RetrievalScope(scope_type="global"), limit=10)
    assert [x.title for x in chunks] == ["code", "wiki"]
