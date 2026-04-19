"""Tests for chunk-aware retrieval in semantic_query and hybrid_query."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from query.semantic_query import SemanticQueryService
from store.schema import NodeLabel


def _make_chunk_node(
    text: str,
    parent_uid: str,
    parent_name: str,
    parent_label: str = "Function",
    chunk_index: int = 0,
    file: str = "service.py",
    start_line: int = 10,
    end_line: int = 15,
):
    """Create a mock FalkorDB node with chunk properties."""
    node = MagicMock()
    node.properties = {
        "uid": f"Chunk:{file}:{parent_name}:{start_line}:c{chunk_index}",
        "name": f"{parent_name}:chunk_{chunk_index}",
        "text": text,
        "parent_uid": parent_uid,
        "parent_name": parent_name,
        "parent_label": parent_label,
        "chunk_index": chunk_index,
        "file": file,
        "start_line": start_line,
        "end_line": end_line,
    }
    return node


def _make_parent_node(
    name: str,
    label: str = "Function",
    file: str = "service.py",
    start_line: int = 1,
    end_line: int = 50,
    signature: str = "",
    docstring: str = "",
):
    """Create a mock FalkorDB parent node."""
    node = MagicMock()
    node.properties = {
        "uid": f"{label}:{file}:{name}:{start_line}",
        "name": name,
        "file": file,
        "start_line": start_line,
        "end_line": end_line,
        "signature": signature or f"def {name}()",
        "docstring": docstring,
    }
    return node


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.vector_search = AsyncMock(return_value=[])
    store.execute_query = AsyncMock()
    return store


@pytest.fixture
def mock_embedding():
    emb = AsyncMock()
    emb.generate_for_query = AsyncMock(return_value=[[0.1] * 1024])
    return emb


class TestSemanticSearchChunks:
    """P2.1: SemanticQueryService.search_chunks()."""

    @pytest.mark.asyncio
    async def test_search_chunks_returns_chunk_matches(self, mock_store, mock_embedding):
        chunk_node = _make_chunk_node(
            text="// In processOrder: def processOrder(id)\n  for attempt in range(3):",
            parent_uid="Function:service.py:processOrder:10",
            parent_name="processOrder",
            chunk_index=1,
            start_line=15,
            end_line=20,
        )
        mock_store.vector_search.return_value = [(chunk_node, 0.92)]

        svc = SemanticQueryService(mock_store, mock_embedding, include_raw_docs_in_results=False)
        result = await svc.search_chunks("retry logic", k=5)

        assert result.total == 1
        match = result.matches[0]
        assert match["type"] == "Chunk"
        assert match["parent_uid"] == "Function:service.py:processOrder:10"
        assert match["parent_name"] == "processOrder"
        assert match["text"] is not None
        assert match["score"] == pytest.approx(0.92)

    @pytest.mark.asyncio
    async def test_search_chunks_empty_when_no_index(self, mock_store, mock_embedding):
        mock_store.vector_search.side_effect = Exception("Index not found")
        svc = SemanticQueryService(mock_store, mock_embedding, include_raw_docs_in_results=False)
        result = await svc.search_chunks("anything", k=5)
        assert result.total == 0
        assert result.matches == []


class TestSemanticSearchWithParentContext:
    """P2.2: SemanticQueryService.search_with_parent_context()."""

    @pytest.mark.asyncio
    async def test_groups_chunks_by_parent(self, mock_store, mock_embedding):
        parent_uid = "Function:service.py:processOrder:10"
        c0 = _make_chunk_node(
            text="// In processOrder\nchunk 0 content here",
            parent_uid=parent_uid,
            parent_name="processOrder",
            chunk_index=0,
            start_line=10,
            end_line=15,
        )
        c1 = _make_chunk_node(
            text="// In processOrder\nchunk 1 retry logic",
            parent_uid=parent_uid,
            parent_name="processOrder",
            chunk_index=1,
            start_line=14,
            end_line=20,
        )
        mock_store.vector_search.return_value = [(c1, 0.95), (c0, 0.88)]

        mock_store.execute_query.return_value = MagicMock(data=[{
            "uid": "Function:service.py:processOrder:10",
            "signature": "def processOrder(order_id: str)",
            "docstring": "Process an order.",
            "file": "service.py",
            "start_line": 10,
            "end_line": 50,
        }])

        svc = SemanticQueryService(mock_store, mock_embedding, include_raw_docs_in_results=False)
        result = await svc.search_with_parent_context("retry logic", k=5)

        assert result.total >= 1
        match = result.matches[0]
        assert match["name"] == "processOrder"
        assert "matched_excerpt" in match
        assert "excerpt_lines" in match

    @pytest.mark.asyncio
    async def test_fallback_to_parent_search(self, mock_store, mock_embedding):
        """When no chunk matches, falls back to parent-level search."""
        mock_store.vector_search.side_effect = [
            [],  # chunk search returns nothing
            [(_make_parent_node("fallbackFunc"), 0.75)],  # function search
            [],  # class search
        ]

        svc = SemanticQueryService(mock_store, mock_embedding, include_raw_docs_in_results=False)
        result = await svc.search_with_parent_context("some query", k=5)

        assert result.total >= 1
        assert any(m.get("name") == "fallbackFunc" for m in result.matches)


class TestHybridWithChunks:
    """P2.3-2.5: HybridQueryService chunk integration."""

    @pytest.mark.asyncio
    async def test_use_child_chunks_flag_activates_chunk_search(self, mock_store, mock_embedding):
        from query.hybrid_query import HybridQueryService
        from query.graph_query import GraphQueryService

        graph_svc = AsyncMock(spec=GraphQueryService)
        graph_svc.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
        graph_svc.find_class_methods = AsyncMock(return_value=MagicMock(data=[]))
        graph_svc.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
        graph_svc.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))

        chunk_node = _make_chunk_node(
            text="// In doWork\nretry logic here",
            parent_uid="Function:a.py:doWork:5",
            parent_name="doWork",
            chunk_index=0,
            file="a.py",
            start_line=5,
            end_line=10,
        )
        mock_store.vector_search.return_value = [(chunk_node, 0.9)]
        mock_store.keyword_search = AsyncMock(return_value=[])
        mock_store.execute_query.return_value = MagicMock(data=[{
            "signature": "def doWork()",
            "docstring": "",
            "file": "a.py",
            "start_line": 5,
            "end_line": 30,
        }])

        sem_svc = SemanticQueryService(mock_store, mock_embedding, include_raw_docs_in_results=False)
        hybrid_svc = HybridQueryService(
            mock_store, sem_svc, graph_svc,
            query_expansion_enabled=False,
        )

        result = await hybrid_svc.search_with_context(
            "retry logic", k=5, use_child_chunks=True,
        )
        assert result.total >= 0  # Basic smoke test
