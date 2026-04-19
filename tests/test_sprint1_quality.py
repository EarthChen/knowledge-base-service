"""Tests for Sprint 1: retrieval quality improvements.

R1: Query Router defaults to enabled
R2: MCP rag_query description mentions reranker
R3: MMR per-file diversity cap
R4: Unified start_line/end_line in semantic results
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── R1: Query Router enabled by default ──────────────────────────────────

def test_r1_query_router_default_true():
    """search_with_context should default use_query_router=True."""
    from query.hybrid_query import HybridQueryService

    sig = inspect.signature(HybridQueryService.search_with_context)
    param = sig.parameters["use_query_router"]
    assert param.default is True, "use_query_router should default to True"


# ── R2: Reranker config mentioned in MCP tool description ────────────────

def test_r2_reranker_in_mcp_description():
    """rag_query tool description should mention reranker configuration."""
    from api.mcp_server import MCP_TOOLS_MANIFEST

    rag_query_tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_query")
    desc = rag_query_tool["description"].lower()
    assert "rerank" in desc, "MCP rag_query description should mention reranker"


# ── R3: Per-file diversity cap ───────────────────────────────────────────

def test_r3_per_file_cap_basic():
    """_apply_per_file_cap should limit results per file."""
    from query.hybrid_query import HybridQueryService

    items = [
        {"name": f"func{i}", "file": "a.py", "score": 1.0 - i * 0.1}
        for i in range(5)
    ]
    result = HybridQueryService._apply_per_file_cap(items, cap=3)
    assert len(result) == 3
    assert all(r["file"] == "a.py" for r in result)


def test_r3_per_file_cap_multi_files():
    """Cap should be applied independently per file."""
    from query.hybrid_query import HybridQueryService

    items = [
        {"name": "a1", "file": "a.py", "score": 0.9},
        {"name": "a2", "file": "a.py", "score": 0.8},
        {"name": "b1", "file": "b.py", "score": 0.85},
        {"name": "a3", "file": "a.py", "score": 0.7},
        {"name": "b2", "file": "b.py", "score": 0.6},
        {"name": "a4", "file": "a.py", "score": 0.5},
        {"name": "b3", "file": "b.py", "score": 0.4},
        {"name": "b4", "file": "b.py", "score": 0.3},
    ]
    result = HybridQueryService._apply_per_file_cap(items, cap=3)
    a_count = sum(1 for r in result if r["file"] == "a.py")
    b_count = sum(1 for r in result if r["file"] == "b.py")
    assert a_count == 3
    assert b_count == 3


def test_r3_per_file_cap_zero_disables():
    """cap<=0 should disable the filter and return all items."""
    from query.hybrid_query import HybridQueryService

    items = [{"name": f"f{i}", "file": "a.py"} for i in range(5)]
    result = HybridQueryService._apply_per_file_cap(items, cap=0)
    assert len(result) == 5, "cap=0 should pass all items through"
    result_neg = HybridQueryService._apply_per_file_cap(items, cap=-1)
    assert len(result_neg) == 5, "cap<0 should also pass all items through"


def test_r3_per_file_cap_preserves_order():
    """Results should maintain their original order after capping."""
    from query.hybrid_query import HybridQueryService

    items = [
        {"name": "a1", "file": "a.py", "score": 0.9},
        {"name": "b1", "file": "b.py", "score": 0.85},
        {"name": "a2", "file": "a.py", "score": 0.8},
    ]
    result = HybridQueryService._apply_per_file_cap(items, cap=2)
    assert [r["name"] for r in result] == ["a1", "b1", "a2"]


# ── R4: Unified reference format (start_line + end_line) ─────────────────

@pytest.mark.asyncio
async def test_r4_semantic_search_includes_start_end_line():
    """All semantic search results should include start_line and end_line."""
    from query.semantic_query import SemanticQueryService
    from store.schema import NodeLabel

    mock_store = MagicMock()
    mock_embedding = AsyncMock()
    mock_embedding.generate_for_query = AsyncMock(return_value=[[0.1] * 10])

    node = MagicMock()
    node.properties = {
        "name": "myFunc",
        "file": "test.py",
        "start_line": 10,
        "end_line": 25,
        "uid": "Function:test.py:myFunc:10",
        "docstring": "A test function",
        "fqn": "test.myFunc",
        "signature": "def myFunc(x)",
    }
    mock_store.vector_search = AsyncMock(return_value=[(node, 0.95)])

    svc = SemanticQueryService(mock_store, mock_embedding, include_raw_docs_in_results=True)
    result = await svc.search_functions("test query", k=5)

    assert len(result.matches) == 1
    m = result.matches[0]
    assert "start_line" in m, "Result must include start_line"
    assert "end_line" in m, "Result must include end_line"
    assert m["start_line"] == 10
    assert m["end_line"] == 25


@pytest.mark.asyncio
async def test_r4_end_line_defaults_to_start_line():
    """When end_line is missing from node properties, default to start_line."""
    from query.semantic_query import SemanticQueryService

    mock_store = MagicMock()
    mock_embedding = AsyncMock()
    mock_embedding.generate_for_query = AsyncMock(return_value=[[0.1] * 10])

    node = MagicMock()
    node.properties = {
        "name": "myFunc",
        "file": "test.py",
        "start_line": 10,
        "uid": "Function:test.py:myFunc:10",
        "docstring": "",
        "fqn": "",
        "signature": "",
    }
    mock_store.vector_search = AsyncMock(return_value=[(node, 0.9)])

    svc = SemanticQueryService(mock_store, mock_embedding, include_raw_docs_in_results=True)
    result = await svc.search_functions("test", k=5)

    m = result.matches[0]
    assert m["start_line"] == 10
    assert m["end_line"] == 10, "end_line should default to start_line when not present"


def test_r3_fuse_expansion_results_has_per_file_cap_param():
    """_fuse_expansion_results should accept per_file_cap parameter."""
    from query.hybrid_query import HybridQueryService

    sig = inspect.signature(HybridQueryService._fuse_expansion_results)
    assert "per_file_cap" in sig.parameters
    assert sig.parameters["per_file_cap"].default == 3
