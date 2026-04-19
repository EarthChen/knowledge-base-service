"""P5.C Document–wiki fusion: related docs query, SOURCE_DOC schema, semantic search filtering."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from query.semantic_query import SemanticQueryService, SemanticResult
from store.falkordb_store import QueryResultWrapper
from store.schema import EdgeType, NodeLabel
from wiki.doc_wiki_fusion import create_source_doc_edges, find_related_docs


def _wrap(rows: list[dict]) -> QueryResultWrapper:
    return QueryResultWrapper(data=rows, raw=[])


@pytest.mark.asyncio
async def test_find_related_docs_returns_matching_documents() -> None:
    async def execute_query(cypher: str, params: dict | None = None) -> QueryResultWrapper:
        assert "REFERENCES" in cypher
        assert params is not None
        assert params.get("entities") == ["Foo", "pkg.Foo"]
        assert params.get("limit") == 5
        return _wrap(
            [
                {"file": "docs/a.md", "content": "body a"},
                {"file": "docs/b.md", "content": "body b"},
            ],
        )

    store = MagicMock()
    store.execute_query = AsyncMock(side_effect=execute_query)

    out = await find_related_docs(store, ["Foo", "pkg.Foo"], limit=5)
    assert out == [
        {"file": "docs/a.md", "content": "body a"},
        {"file": "docs/b.md", "content": "body b"},
    ]
    store.execute_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_related_docs_returns_empty_when_no_matches() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=_wrap([]))

    out = await find_related_docs(store, ["Unknown"], limit=3)
    assert out == []


def test_source_doc_edge_type_exists_in_schema() -> None:
    assert EdgeType.SOURCE_DOC == "SOURCE_DOC"
    assert "SOURCE_DOC" in [e.value for e in EdgeType]


@pytest.mark.asyncio
async def test_search_all_respects_include_raw_docs_in_results_false() -> None:
    async def fake_search(query_text: str, label: NodeLabel, k: int) -> SemanticResult:
        if label == NodeLabel.DOCUMENT:
            return SemanticResult(
                matches=[{"type": "Document", "score": 0.99, "name": "readme", "file": "README.md"}],
                query_text=query_text,
                total=1,
            )
        if label == NodeLabel.FUNCTION:
            return SemanticResult(
                matches=[{"type": "Function", "score": 0.5, "name": "foo", "file": "f.py"}],
                query_text=query_text,
                total=1,
            )
        return SemanticResult(matches=[], query_text=query_text, total=0)

    svc = SemanticQueryService(MagicMock(), MagicMock(), include_raw_docs_in_results=False)
    svc._search_by_label = AsyncMock(side_effect=fake_search)  # type: ignore[method-assign]

    res = await svc.search_all("hello", k=5)
    types = {m.get("type") for m in res.matches}
    assert "Document" not in types
    assert "Function" in types


@pytest.mark.asyncio
async def test_search_all_includes_document_hits_when_include_raw_docs_true() -> None:
    async def fake_search(query_text: str, label: NodeLabel, k: int) -> SemanticResult:
        if label == NodeLabel.DOCUMENT:
            return SemanticResult(
                matches=[{"type": "Document", "score": 0.99, "name": "readme", "file": "README.md"}],
                query_text=query_text,
                total=1,
            )
        if label == NodeLabel.FUNCTION:
            return SemanticResult(
                matches=[{"type": "Function", "score": 0.5, "name": "foo", "file": "f.py"}],
                query_text=query_text,
                total=1,
            )
        return SemanticResult(matches=[], query_text=query_text, total=0)

    svc = SemanticQueryService(MagicMock(), MagicMock(), include_raw_docs_in_results=True)
    svc._search_by_label = AsyncMock(side_effect=fake_search)  # type: ignore[method-assign]

    res = await svc.search_all("hello", k=5)
    types = {m.get("type") for m in res.matches}
    assert "Document" in types
    assert "Function" in types


@pytest.mark.asyncio
async def test_create_source_doc_edges_batched() -> None:
    calls: list[tuple[str, dict]] = []

    async def execute_query(cypher: str, params: dict | None = None) -> QueryResultWrapper:
        calls.append((cypher, params or {}))
        assert "SOURCE_DOC" in cypher
        assert "WikiPage" in cypher
        assert "Document" in cypher
        assert "UNWIND" in cypher
        assert params is not None
        assert params["docs"] == ["d1.md", "d2.md"]
        assert "d.repository = $repository" in cypher
        return _wrap([{"cnt": 2}])

    store = MagicMock()
    store.execute_query = AsyncMock(side_effect=execute_query)

    n = await create_source_doc_edges(
        store,
        repository="r1",
        wiki_page_path="wiki/p.md",
        docs=[{"file": "d1.md", "content": "x"}, {"file": "d2.md", "content": "y"}],
    )
    assert n == 2
    store.execute_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_source_doc_edges_skips_empty_files() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock()

    n = await create_source_doc_edges(
        store,
        repository="r1",
        wiki_page_path="wiki/p.md",
        docs=[{"file": "", "content": "x"}, {"file": "  ", "content": "y"}],
    )
    assert n == 0
    store.execute_query.assert_not_awaited()

