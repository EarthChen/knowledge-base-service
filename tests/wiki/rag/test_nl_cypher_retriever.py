from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever, _format_cypher_row
from wiki.rag.protocol import RetrievalScope


def test_format_cypher_row_with_signature():
    row = {
        "name": "authenticate",
        "type": "Function",
        "file": "u.py",
        "line": 10,
        "signature": "def authenticate() -> None",
    }
    assert _format_cypher_row(row) == "[Function] authenticate (u.py:10) - def authenticate() -> None"


def test_format_cypher_row_minimal():
    row = {"name": "onlyname"}
    assert _format_cypher_row(row) == "onlyname"


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
        return_value=MagicMock(data=[{"name": "FallbackEntity", "type": "Function"}], rows=[]),
    )
    svc.find_call_chain = AsyncMock(
        return_value=MagicMock(data=[], params={"_edges": []}),
    )
    return svc


@pytest.mark.asyncio
async def test_cypher_results_become_graph_cypher_chunks(mock_hybrid, mock_graph):
    nl = AsyncMock()
    nl.query = AsyncMock(
        return_value={
            "question": "q",
            "cypher": "MATCH (n) RETURN n LIMIT 1",
            "results": [
                {
                    "name": "foo",
                    "type": "Function",
                    "file": "a.py",
                    "line": 3,
                    "signature": "def foo(): ...",
                },
            ],
            "total": 1,
        },
    )
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph, nl_cypher=nl)
    scope = RetrievalScope(scope_type="repository", repository="myrepo")
    chunks = await retriever.retrieve(["who calls foo"], scope)

    nl.query.assert_awaited_once()
    assert nl.query.await_args.kwargs.get("repository") == "myrepo"
    mock_graph.find_entity.assert_not_awaited()

    cypher_chunks = [c for c in chunks if c.source == "graph_cypher"]
    assert len(cypher_chunks) == 1
    assert "[Function] foo (a.py:3) - def foo(): ..." in cypher_chunks[0].content


@pytest.mark.asyncio
async def test_cypher_failure_falls_through_to_entity_lookup(mock_hybrid, mock_graph):
    nl = AsyncMock()
    nl.query = AsyncMock(
        return_value={
            "question": "q",
            "cypher": "",
            "error": "validation failed",
            "results": [],
            "total": 0,
        },
    )
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph, nl_cypher=nl)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    await retriever.retrieve(["something"], scope)

    nl.query.assert_awaited()
    mock_graph.find_entity.assert_awaited()


@pytest.mark.asyncio
async def test_empty_cypher_results_fall_through_to_entity_lookup(mock_hybrid, mock_graph):
    nl = AsyncMock()
    nl.query = AsyncMock(
        return_value={
            "question": "q",
            "cypher": "MATCH (n) RETURN n LIMIT 0",
            "results": [],
            "total": 0,
        },
    )
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph, nl_cypher=nl)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    await retriever.retrieve(["no rows"], scope)

    nl.query.assert_awaited()
    mock_graph.find_entity.assert_awaited()


@pytest.mark.asyncio
async def test_nl_cypher_exception_falls_through(mock_hybrid, mock_graph):
    nl = AsyncMock()
    nl.query = AsyncMock(side_effect=RuntimeError("boom"))
    retriever = HybridGraphRetriever(mock_hybrid, mock_graph, nl_cypher=nl)
    scope = RetrievalScope(scope_type="business", business_id="biz-1")
    # Query must yield at least one entity candidate so the graph leg runs.
    await retriever.retrieve(["FallbackEntity flow"], scope)

    mock_graph.find_entity.assert_awaited()
