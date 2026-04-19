"""Tests for SearchStore (BM25 / full-text + delegations)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from store.search_store import SearchStore
from store.schema import NodeLabel


@pytest.fixture
def mock_base_store():
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
    store.vector_search = AsyncMock(return_value=[])
    store.keyword_search = AsyncMock(return_value=[])
    return store


class TestSearchStoreEnsureIndexes:
    @pytest.mark.asyncio
    async def test_ensure_fulltext_indexes_calls_create_for_each_label(self, mock_base_store):
        mock_base_store.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
        ss = SearchStore(mock_base_store)

        await ss.ensure_fulltext_indexes()

        queries = [c.args[0] for c in mock_base_store.execute_query.call_args_list]
        assert any("createNodeIndex('Function'" in q for q in queries)
        assert any("createNodeIndex('Class'" in q for q in queries)
        assert any("createNodeIndex('Module'" in q for q in queries)
        assert any("createNodeIndex('Document'" in q for q in queries)
        assert any("createNodeIndex('Chunk'" in q for q in queries)
        assert any("createNodeIndex('WikiPage'" in q for q in queries)

    @pytest.mark.asyncio
    async def test_ensure_fulltext_indexes_swallows_duplicate_errors(self, mock_base_store):
        calls = []

        async def fail_first_create(q: str, params=None):
            calls.append(q)
            if "createNodeIndex('Function'" in q:
                raise RuntimeError("Index already exists")
            return QueryResultWrapper(data=[], raw=[])

        mock_base_store.execute_query = AsyncMock(side_effect=fail_first_create)
        ss = SearchStore(mock_base_store)

        await ss.ensure_fulltext_indexes()

        assert len([c for c in calls if "createNodeIndex" in c]) >= 6


class TestSearchStoreFulltextSearch:
    @pytest.mark.asyncio
    async def test_fulltext_search_runs_query_nodes_per_label(self, mock_base_store):
        async def exec_side(cypher: str, params=None):
            if "queryNodes('Function'" in cypher:
                return QueryResultWrapper(
                    data=[
                        {
                            "uid": "f1",
                            "name": "foo",
                            "file": "a.py",
                            "line": 1,
                            "type": "Function",
                            "signature": "def foo():",
                            "docstring": "d",
                            "fqn": "m.foo",
                            "score": 0.9,
                        }
                    ],
                    raw=[],
                )
            return QueryResultWrapper(data=[], raw=[])

        mock_base_store.execute_query = AsyncMock(side_effect=exec_side)
        ss = SearchStore(mock_base_store)

        rows = await ss.fulltext_search("bar", labels=["Function"], limit=5)

        assert len(rows) == 1
        assert rows[0]["uid"] == "f1"
        assert rows[0]["score"] == pytest.approx(0.9)
        fts_calls = [c for c in mock_base_store.execute_query.call_args_list if "queryNodes" in str(c)]
        assert fts_calls

    @pytest.mark.asyncio
    async def test_fulltext_search_passes_repo_language_filters(self, mock_base_store):
        captured: list[tuple[str, dict | None]] = []

        async def cap(cypher: str, params=None):
            captured.append((cypher, params))
            return QueryResultWrapper(data=[], raw=[])

        mock_base_store.execute_query = AsyncMock(side_effect=cap)
        ss = SearchStore(mock_base_store)

        await ss.fulltext_search(
            "x",
            labels=["Class"],
            limit=3,
            repository="my-repo",
            language="python",
        )

        assert captured
        _cy, params = captured[0]
        assert params is not None
        assert params.get("repo") == "my-repo"
        assert params.get("lang") == "python"
        cy = captured[0][0]
        assert "node.repository = $repo" in cy
        assert "node.language = $lang" in cy

    @pytest.mark.asyncio
    async def test_fulltext_search_default_labels(self, mock_base_store):
        labels_used: list[str] = []

        async def track(cypher: str, params=None):
            if "queryNodes" in cypher:
                for lbl in ("Function", "Class", "Module", "Document"):
                    if f"queryNodes('{lbl}'" in cypher:
                        labels_used.append(lbl)
            return QueryResultWrapper(data=[], raw=[])

        mock_base_store.execute_query = AsyncMock(side_effect=track)
        ss = SearchStore(mock_base_store)

        await ss.fulltext_search("q", limit=10)

        assert set(labels_used) == {"Function", "Class", "Module", "Document"}


class TestSearchStoreDelegations:
    @pytest.mark.asyncio
    async def test_vector_search_delegates(self, mock_base_store):
        mock_base_store.vector_search = AsyncMock(return_value=[("n", 0.5)])
        ss = SearchStore(mock_base_store)

        out = await ss.vector_search(
            NodeLabel.FUNCTION,
            [0.1, 0.2],
            k=3,
            repository="r",
            language="go",
        )

        assert out == [("n", 0.5)]
        mock_base_store.vector_search.assert_called_once_with(
            NodeLabel.FUNCTION,
            [0.1, 0.2],
            3,
            "embedding",
            repository="r",
            language="go",
        )

    @pytest.mark.asyncio
    async def test_keyword_search_delegates(self, mock_base_store):
        mock_base_store.keyword_search = AsyncMock(return_value=[{"uid": "u"}])
        ss = SearchStore(mock_base_store)

        out = await ss.keyword_search(
            "kw",
            k=7,
            exact_only=True,
            repository="r",
            language="java",
        )

        assert out == [{"uid": "u"}]
        mock_base_store.keyword_search.assert_called_once_with(
            "kw",
            7,
            exact_only=True,
            repository="r",
            language="java",
        )
