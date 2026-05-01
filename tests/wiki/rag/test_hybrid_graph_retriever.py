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
        return_value=MagicMock(data=[{"name": "Auth", "type": "concept"}], rows=[])
    )
    svc.find_call_chain = AsyncMock(
        return_value=MagicMock(
            data=[
                {"name": "Auth", "file": "a.py", "line": 1},
                {"name": "Other", "file": "b.py", "line": 2},
            ],
            params={"_edges": [{"source": "Auth:1", "target": "Other:2"}]},
        ),
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


@pytest.mark.asyncio
async def test_graph_leg_extracts_camelcase_entities(mock_hybrid):
    graph = AsyncMock()
    graph.find_entity = AsyncMock(return_value=MagicMock(data=[], rows=[]))
    graph.find_call_chain = AsyncMock(
        return_value=MagicMock(data=[], params={"_edges": []}),
    )
    retriever = HybridGraphRetriever(mock_hybrid, graph)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    await retriever.retrieve(["how does UserAuthService handle login"], scope)

    searched = {c.args[0] for c in graph.find_entity.call_args_list}
    assert "UserAuthService" in searched
    assert "login" in searched


@pytest.mark.asyncio
async def test_graph_leg_traverses_call_chain(mock_hybrid):
    graph = AsyncMock()
    graph.find_entity = AsyncMock(
        return_value=MagicMock(
            data=[{"name": "authenticate", "type": "Function", "file": "u.py", "line": 10}],
            rows=[],
        ),
    )
    graph.find_call_chain = AsyncMock(
        return_value=MagicMock(
            data=[
                {"name": "authenticate", "file": "u.py", "line": 10},
                {"name": "JWTProvider", "file": "j.py", "line": 5},
            ],
            params={"_edges": [{"source": "authenticate:10", "target": "JWTProvider:5"}]},
        ),
    )
    retriever = HybridGraphRetriever(mock_hybrid, graph)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    chunks = await retriever.retrieve(["authenticate user"], scope)

    graph.find_call_chain.assert_awaited()
    assert graph.find_call_chain.await_args.args[0] == "authenticate"
    assert graph.find_call_chain.await_args.kwargs.get("depth") == 1
    assert any("JWTProvider" in c.content and "authenticate" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_graph_leg_skips_common_words(mock_hybrid):
    graph = AsyncMock()
    graph.find_entity = AsyncMock(return_value=MagicMock(data=[], rows=[]))
    graph.find_call_chain = AsyncMock(
        return_value=MagicMock(data=[], params={"_edges": []}),
    )
    retriever = HybridGraphRetriever(mock_hybrid, graph)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    await retriever.retrieve(["how does the what work"], scope)

    for call in graph.find_entity.call_args_list:
        assert call.args[0] not in {"how", "does", "the", "what"}


@pytest.mark.asyncio
async def test_retrieve_global_scope_no_repository(mock_hybrid):
    """HybridGraphRetriever should still return results for global scope without repository."""
    retriever = HybridGraphRetriever(mock_hybrid)
    scope = RetrievalScope(scope_type="global")
    chunks = await retriever.retrieve(["general question"], scope)
    assert len(chunks) >= 1
    mock_hybrid.search_with_context.assert_called_once()
    assert mock_hybrid.search_with_context.await_args.kwargs.get("repository") is None


@pytest.mark.asyncio
async def test_retrieve_passes_scope_repository_to_hybrid(mock_hybrid, mock_graph):
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph)
    scope = RetrievalScope(scope_type="repository", repository="repo-one")
    await retriever.retrieve(["auth"], scope)
    assert mock_hybrid.search_with_context.await_args.kwargs.get("repository") == "repo-one"
