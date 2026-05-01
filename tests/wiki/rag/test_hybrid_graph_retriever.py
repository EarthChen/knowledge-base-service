from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever
from wiki.rag.protocol import RetrievalScope


@pytest.fixture
def mock_hybrid():
    svc = AsyncMock()
    svc.search_with_context = AsyncMock(
        return_value=[
            MagicMock(content="hybrid result", title="page1", path="/wiki/page1", score=0.9),
        ]
    )
    return svc


@pytest.fixture
def mock_graph():
    svc = AsyncMock()
    svc.find_entity = AsyncMock(
        return_value=MagicMock(rows=[{"name": "Auth", "type": "concept"}])
    )
    return svc


@pytest.mark.asyncio
async def test_retrieve_combines_hybrid_and_graph(mock_hybrid, mock_graph):
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    chunks = await retriever.retrieve(["auth flow"], scope)
    assert len(chunks) >= 2
    assert any("hybrid result" in c.content for c in chunks)
    assert any("Auth" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_retrieve_multiple_queries(mock_hybrid, mock_graph):
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    chunks = await retriever.retrieve(["query1", "query2"], scope)
    assert mock_hybrid.search_with_context.call_count == 2
