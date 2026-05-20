"""Tests for Sprint 2 U1: Cypher-level repository + language filtering.

Verifies that filters are properly injected into Cypher queries at
the store layer, passed through semantic and hybrid query layers, and
exposed on the API/MCP interfaces.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Store layer: vector_search filter parameters ─────────────────────────

def test_vector_search_accepts_repository_language():
    """vector_search should accept repository and language keyword arguments."""
    from store.falkordb_store import FalkorDBStore

    sig = inspect.signature(FalkorDBStore.vector_search)
    assert "repository" in sig.parameters
    assert "language" in sig.parameters


def test_keyword_search_accepts_repository_language():
    """keyword_search should accept repository and language keyword arguments."""
    from store.falkordb_store import FalkorDBStore

    sig = inspect.signature(FalkorDBStore.keyword_search)
    assert "repository" in sig.parameters
    assert "language" in sig.parameters


def test_cypher_escape():
    """_cypher_escape should escape single quotes and backslashes."""
    from store.falkordb_store import _cypher_escape

    assert _cypher_escape("hello") == "hello"
    assert _cypher_escape("it's") == "it\\'s"
    assert _cypher_escape("a\\b") == "a\\\\b"
    assert _cypher_escape("") == ""


# ── Semantic layer: filters pass through ─────────────────────────────────

def test_search_by_label_accepts_filters():
    """SemanticQueryService._search_by_label should accept repository/language."""
    from query.semantic_query import SemanticQueryService

    sig = inspect.signature(SemanticQueryService._search_by_label)
    assert "repository" in sig.parameters
    assert "language" in sig.parameters


def test_search_all_accepts_filters():
    """search_all should accept repository/language."""
    from query.semantic_query import SemanticQueryService

    sig = inspect.signature(SemanticQueryService.search_all)
    assert "repository" in sig.parameters
    assert "language" in sig.parameters


def test_search_with_parent_context_accepts_filters():
    """search_with_parent_context should accept repository/language."""
    from query.semantic_query import SemanticQueryService

    sig = inspect.signature(SemanticQueryService.search_with_parent_context)
    assert "repository" in sig.parameters
    assert "language" in sig.parameters


# ── Hybrid layer: filters pass through ───────────────────────────────────

def test_hybrid_search_with_context_accepts_filters():
    """search_with_context should accept repository/language."""
    from query.hybrid_query import HybridQueryService

    sig = inspect.signature(HybridQueryService.search_with_context)
    assert "repository" in sig.parameters
    assert "language" in sig.parameters


def test_hybrid_keyword_search_multi_accepts_filters():
    """_keyword_search_multi should accept repository/language."""
    from query.hybrid_query import HybridQueryService

    sig = inspect.signature(HybridQueryService._keyword_search_multi)
    assert "repository" in sig.parameters
    assert "language" in sig.parameters


# ── API/MCP layer ────────────────────────────────────────────────────────

def test_hybrid_search_request_has_filters():
    """HybridSearchRequest should have repository and language fields."""
    from main import HybridSearchRequest

    req = HybridSearchRequest(query="test", repository="my-repo", language="python")
    assert req.repository == "my-repo"
    assert req.language == "python"


def test_hybrid_search_request_filters_optional():
    """repository and language should be optional (default None)."""
    from main import HybridSearchRequest

    req = HybridSearchRequest(query="test")
    assert req.repository is None
    assert req.language is None


def test_mcp_rag_query_has_repository_language():
    """MCP rag_query tool schema should include repository and language params."""
    from api.mcp_server import MCP_TOOLS_MANIFEST

    rag_query_tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_query")
    props = rag_query_tool["inputSchema"]["properties"]
    assert "repository" in props, "rag_query should have repository param"
    assert "language" in props, "rag_query should have language param"


# ── Integration: vector_search constructs correct Cypher ────────────────

@pytest.mark.asyncio
async def test_vector_search_cypher_includes_where_filters():
    """When repository/language provided, vector_search Cypher should include WHERE."""
    from store.falkordb_store import FalkorDBStore
    from store.schema import NodeLabel

    store = FalkorDBStore.__new__(FalkorDBStore)
    store._graph = MagicMock()

    captured: list[tuple[str, dict[str, Any]]] = []

    def capture_query(q, **kwargs):
        captured.append((q, kwargs.get("params") or {}))
        mock_result = MagicMock()
        mock_result.result_set = []
        return mock_result

    store._graph.query = capture_query

    await store.vector_search(
        NodeLabel.FUNCTION,
        [0.1] * 3,
        k=5,
        repository="my-repo",
        language="python",
    )

    assert len(captured) == 1
    cypher, params = captured[0]
    assert "node.repository = $repo" in cypher
    assert "node.language = $lang" in cypher
    assert params["repo"] == "my-repo"
    assert params["lang"] == "python"
    assert "WHERE" in cypher


@pytest.mark.asyncio
async def test_vector_search_no_filters_no_where():
    """Without filters, vector_search should not add WHERE clause."""
    from store.falkordb_store import FalkorDBStore
    from store.schema import NodeLabel

    store = FalkorDBStore.__new__(FalkorDBStore)
    store._graph = MagicMock()

    captured_queries: list[str] = []

    def capture_query(q, **kwargs):
        captured_queries.append(q)
        mock_result = MagicMock()
        mock_result.result_set = []
        return mock_result

    store._graph.query = capture_query

    await store.vector_search(NodeLabel.FUNCTION, [0.1] * 3, k=5)

    assert len(captured_queries) == 1
    cypher = captured_queries[0]
    assert "WHERE" not in cypher
