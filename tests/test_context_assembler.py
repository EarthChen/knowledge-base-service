"""Tests for query.context_assembler.ContextAssembler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from query.context_assembler import ContextAssembler


def test_assembler_accepts_resolver_budget():
    from wiki.token_budget import TokenBudgetResolver

    r = TokenBudgetResolver(base=30_000)
    budget = r.budget("assembly")
    assert budget == 8_100


@pytest.fixture
def mock_store():
    return AsyncMock()


@pytest.fixture
def mock_hybrid():
    return AsyncMock()


@pytest.fixture
def mock_graph():
    return AsyncMock()


async def _store_dispatch_entity_then_empty_wiki(query: str, _params=None):
    if "WikiPage" in (query or ""):
        return MagicMock(data=[])
    return MagicMock(
        data=[
            {
                "uid": "fn-1",
                "name": "foo",
                "type": "Function",
                "file": "f.py",
                "start_line": 1,
                "end_line": 5,
                "code_snippet": "def foo(): pass",
                "docstring": "doc",
                "signature": "foo()",
                "repository": "r1",
            },
        ],
    )


@pytest.mark.asyncio
async def test_assemble_returns_required_sections(mock_store, mock_hybrid, mock_graph):
    matches = [
        {
            "name": "foo",
            "type": "Function",
            "uid": "fn-1",
            "file": "f.py",
            "line": 1,
            "repository": "r1",
            "score": 1.0,
            "confidence": 1.0,
            "match_source": "keyword",
        },
    ]
    mock_hybrid.search_with_context = AsyncMock(
        return_value={
            "results": matches,
            "semantic_matches": matches,
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.9,
            "no_results_reason": "",
        },
    )
    mock_store.execute_query = AsyncMock(side_effect=_store_dispatch_entity_then_empty_wiki)
    mock_graph.find_call_chain = AsyncMock(return_value=MagicMock(data=[{"name": "caller"}]))
    mock_graph.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    mock_graph.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))

    asm = ContextAssembler(mock_store, mock_hybrid, mock_graph)
    out = await asm.assemble("foo", repository="r1", max_tokens=8000)

    assert set(out.keys()) >= {
        "entity",
        "call_chain",
        "hierarchy",
        "business_flows",
        "wiki_content",
        "confidence",
    }
    assert out["entity"].get("name") == "foo"
    assert "upstream" in out["call_chain"] and "downstream" in out["call_chain"]
    assert "parents" in out["hierarchy"] and "children" in out["hierarchy"]
    assert isinstance(out["business_flows"], list)
    assert isinstance(out["confidence"], float)


@pytest.mark.asyncio
async def test_max_tokens_truncates_wiki_first(mock_store, mock_hybrid, mock_graph):
    huge = "word " * 5000

    async def dispatch(q, _params=None):
        qs = q or ""
        if "WikiPage" in qs:
            return MagicMock(data=[{"title": "t", "path": "p.md", "content": huge}])
        return MagicMock(
            data=[
                {
                    "uid": "c1",
                    "name": "bar",
                    "type": "Class",
                    "file": "c.py",
                    "start_line": 1,
                    "end_line": 2,
                    "code_snippet": "class Bar: pass",
                    "docstring": "",
                    "signature": "",
                    "repository": "r1",
                },
            ],
        )

    matches = [
        {
            "name": "bar",
            "type": "Class",
            "uid": "c1",
            "file": "c.py",
            "line": 1,
            "repository": "r1",
            "score": 1.0,
            "confidence": 1.0,
            "match_source": "keyword",
        },
    ]
    mock_hybrid.search_with_context = AsyncMock(
        return_value={
            "results": matches,
            "semantic_matches": matches,
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.5,
            "no_results_reason": "",
        },
    )
    mock_store.execute_query = AsyncMock(side_effect=dispatch)
    mock_graph.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
    mock_graph.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    mock_graph.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))

    asm = ContextAssembler(mock_store, mock_hybrid, mock_graph)
    out = await asm.assemble("bar", repository="r1", max_tokens=400)
    assert out["entity"].get("code_snippet")
    assert len(out.get("wiki_content") or "") < len(huge)


@pytest.mark.asyncio
async def test_nonexistent_entity_graceful_empty(mock_store, mock_hybrid, mock_graph):
    mock_hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )
    mock_graph.find_entity = AsyncMock(return_value=MagicMock(data=[]))

    asm = ContextAssembler(mock_store, mock_hybrid, mock_graph)
    out = await asm.assemble("does_not_exist_xyz")

    assert out["entity"] == {}
    assert out["confidence"] == 0.0
    assert out["call_chain"] == {"upstream": [], "downstream": []}
