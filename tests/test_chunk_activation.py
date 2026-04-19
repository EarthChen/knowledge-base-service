"""Tests for Phase 3: chunk activation, config wiring, and MCP enhancement."""

from __future__ import annotations

import pytest


class TestConfigDefaults:
    """P3.1: use_child_chunks defaults to True."""

    def test_use_child_chunks_default_true(self):
        from config import HybridSearchConfig

        cfg = HybridSearchConfig()
        assert cfg.use_child_chunks is True

    def test_child_chunk_window_defaults(self):
        from config import HybridSearchConfig

        cfg = HybridSearchConfig()
        assert cfg.child_chunk_window_chars == 800
        assert cfg.child_chunk_stride_chars == 600
        assert cfg.child_chunk_min_parent_chars == 400


class TestContextAssemblerExcerpt:
    """P3.3: get_complete_context includes matched_excerpt."""

    def test_empty_payload_has_excerpt_fields(self):
        from unittest.mock import AsyncMock
        from query.context_assembler import ContextAssembler

        store = AsyncMock()
        hybrid = AsyncMock()
        graph = AsyncMock()
        assembler = ContextAssembler(store, hybrid, graph)
        payload = assembler._empty_payload(0.0)
        assert "matched_excerpt" in payload
        assert "excerpt_lines" in payload
        assert payload["matched_excerpt"] == ""
        assert payload["excerpt_lines"] == []

    @pytest.mark.asyncio
    async def test_assemble_propagates_excerpt(self):
        from unittest.mock import AsyncMock, MagicMock
        from query.context_assembler import ContextAssembler
        from query.hybrid_query import HybridResult

        store = AsyncMock()
        graph = AsyncMock()
        hybrid = AsyncMock()

        hybrid.search_with_context.return_value = HybridResult(
            semantic_matches=[{
                "name": "processOrder",
                "type": "Function",
                "file": "service.py",
                "line": 10,
                "score": 0.9,
                "uid": "Function:service.py:processOrder:10",
                "matched_excerpt": "// In processOrder\nretry logic here",
                "excerpt_lines": [15, 20],
                "signature": "def processOrder()",
                "docstring": "Process order.",
            }],
            graph_context=[],
            query_text="processOrder",
            total=1,
            confidence=0.9,
            no_results_reason="",
        )
        graph.find_call_chain.return_value = MagicMock(data=[])
        graph.find_inheritance_tree.return_value = MagicMock(data=[])
        graph.find_flows_for_function.return_value = MagicMock(data=[])

        store.execute_query.return_value = MagicMock(data=[{
            "uid": "Function:service.py:processOrder:10",
            "name": "processOrder",
            "type": "Function",
            "file": "service.py",
            "start_line": 10,
            "end_line": 50,
            "code_snippet": "def processOrder():\n    pass",
            "docstring": "Process order.",
            "signature": "def processOrder()",
            "repository": "myrepo",
        }])

        assembler = ContextAssembler(store, hybrid, graph)
        result = await assembler.assemble("processOrder", max_tokens=8000)

        assert result["matched_excerpt"] == "// In processOrder\nretry logic here"
        assert result["excerpt_lines"] == [15, 20]
        assert result["confidence"] > 0.5


class TestSchemaChunkPresent:
    """Verify Chunk is in schema and vector index configs."""

    def test_chunk_in_node_label(self):
        from store.schema import NodeLabel

        assert hasattr(NodeLabel, "CHUNK")
        assert NodeLabel.CHUNK == "Chunk"

    def test_chunk_in_vector_index(self):
        from store.schema import VECTOR_INDEX_CONFIGS, NodeLabel

        labels = {c["label"] for c in VECTOR_INDEX_CONFIGS}
        assert NodeLabel.CHUNK in labels
