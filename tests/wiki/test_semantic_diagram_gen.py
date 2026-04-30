"""Tests for LLM semantic diagram generation."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.models import DiagramType, PageType
from wiki.semantic_diagram_gen import SemanticDiagramGenerator


def test_sequence_diagram_type_exists():
    assert DiagramType.SEQUENCE_DIAGRAM == "sequenceDiagram"
    assert DiagramType("sequenceDiagram") == DiagramType.SEQUENCE_DIAGRAM


def _make_node(label: NodeLabel = NodeLabel.MODULE, uid: str = "test:mod:main") -> GraphNode:
    return GraphNode(uid=uid, label=label, properties={"name": "main"})


def _make_edges(call_count: int) -> list[GraphEdge]:
    return [
        GraphEdge(
            source_uid="test:mod:main",
            target_uid=f"test:mod:dep{i}",
            edge_type=EdgeType.CALLS,
            properties={},
        )
        for i in range(call_count)
    ]


def _make_page_data(
    node: GraphNode | None = None,
    edges: list[GraphEdge] | None = None,
    methods: list | None = None,
):
    pd = MagicMock()
    pd.node = node or _make_node()
    pd.edges = edges or []
    pd.methods = methods or []
    pd.children = []
    pd.code_snippets = []
    pd.related_chunks = []
    return pd


class TestValidateAndClean:
    def test_valid_sequence_diagram(self):
        raw = "sequenceDiagram\n    A->>B: call\n    B-->>A: response"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None
        assert result.startswith("sequenceDiagram")

    def test_strips_markdown_fences(self):
        raw = "```mermaid\nsequenceDiagram\n    A->>B: call\n```"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None
        assert not result.startswith("```")
        assert result.startswith("sequenceDiagram")

    def test_invalid_mermaid_returns_none(self):
        raw = "This is just text, not a diagram"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is None

    def test_empty_input_returns_none(self):
        result = SemanticDiagramGenerator._validate_and_clean("")
        assert result is None

    def test_strips_triple_backtick_without_mermaid_tag(self):
        raw = "```\nsequenceDiagram\n    A->>B: call\n```"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None
        assert result.startswith("sequenceDiagram")

    def test_max_lines_exceeded_returns_none(self):
        lines = ["sequenceDiagram"] + [f"    A->>B: step{i}" for i in range(200)]
        raw = "\n".join(lines)
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is None

    def test_valid_flowchart(self):
        raw = "flowchart TD\n    A --> B"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None

    def test_valid_state_diagram(self):
        raw = "stateDiagram-v2\n    [*] --> Active"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None


class TestShouldGenerate:
    def test_module_with_enough_calls_triggers(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(4))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "full") is True

    def test_module_with_few_calls_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(2))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "full") is False

    def test_module_with_exact_threshold_triggers(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(3))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "full") is True

    def test_class_with_enough_methods_and_calls_triggers(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        methods = [MagicMock() for _ in range(6)]
        pd = _make_page_data(
            node=_make_node(NodeLabel.CLASS, "test:cls:MyClass"),
            edges=_make_edges(3),
            methods=methods,
        )
        assert gen._should_generate(pd, PageType.CLASS_DETAIL, "full") is True

    def test_class_with_few_methods_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        methods = [MagicMock() for _ in range(2)]
        pd = _make_page_data(
            node=_make_node(NodeLabel.CLASS, "test:cls:Small"),
            edges=_make_edges(3),
            methods=methods,
        )
        assert gen._should_generate(pd, PageType.CLASS_DETAIL, "full") is False

    def test_structure_mode_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(10))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "structure") is False

    def test_no_llm_skips(self):
        gen = SemanticDiagramGenerator(llm=None)
        pd = _make_page_data(edges=_make_edges(10))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "full") is False

    def test_unsupported_page_type_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(10))
        assert gen._should_generate(pd, PageType.API_REFERENCE, "full") is False

    def test_topic_with_llm_and_full_mode_triggers(self):
        """TOPIC pages should run semantic diagram generation like overview pages."""
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=[])  # no CALLS edges required for TOPIC
        assert gen._should_generate(pd, PageType.TOPIC, "full") is True


class TestGenerate:
    def test_successful_generation(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value="sequenceDiagram\n    A->>B: process\n    B-->>A: result"
        )

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=_make_edges(5))
            entity_digest = "- Label: module\n- UID: test:mod:main\n- Calls out to:\n  -> dep0\n  -> dep1"
            diagrams = await gen.generate(pd, PageType.MODULE_OVERVIEW, entity_digest, "full")
            assert len(diagrams) == 1
            assert diagrams[0].diagram_type == DiagramType.SEQUENCE_DIAGRAM
            assert "sequenceDiagram" in diagrams[0].content
            assert diagrams[0].title == "Module interaction flow"

        asyncio.run(_run())

    def test_llm_failure_returns_empty(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM down"))

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=_make_edges(5))
            diagrams = await gen.generate(pd, PageType.MODULE_OVERVIEW, "digest", "full")
            assert diagrams == []

        asyncio.run(_run())

    def test_invalid_mermaid_filtered(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="This is not valid mermaid")

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=_make_edges(5))
            diagrams = await gen.generate(pd, PageType.MODULE_OVERVIEW, "digest", "full")
            assert diagrams == []

        asyncio.run(_run())

    def test_skips_when_not_enough_edges(self):
        mock_llm = AsyncMock()

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=_make_edges(1))
            diagrams = await gen.generate(pd, PageType.MODULE_OVERVIEW, "digest", "full")
            assert diagrams == []
            mock_llm.generate.assert_not_called()

        asyncio.run(_run())

    def test_class_detail_title(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value="sequenceDiagram\n    A->>B: call\n    B-->>A: result"
        )

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            methods = [MagicMock() for _ in range(6)]
            pd = _make_page_data(
                node=_make_node(NodeLabel.CLASS, "test:cls:MyClass"),
                edges=_make_edges(3),
                methods=methods,
            )
            diagrams = await gen.generate(pd, PageType.CLASS_DETAIL, "digest", "full")
            assert len(diagrams) == 1
            assert diagrams[0].title == "Class interaction flow"

        asyncio.run(_run())

    def test_invalid_mermaid_logs_warning(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="This is not valid mermaid")

        async def _run():
            with patch("wiki.semantic_diagram_gen.log") as mock_log:
                gen = SemanticDiagramGenerator(llm=mock_llm)
                pd = _make_page_data(edges=_make_edges(5))
                await gen.generate(pd, PageType.MODULE_OVERVIEW, "digest", "full")
                mock_log.warning.assert_called()
                events = [c.args[0] for c in mock_log.warning.call_args_list if c.args]
                assert "semantic_diagram_invalid_mermaid" in events
                mock_log.info.assert_not_called()
                mock_log.debug.assert_not_called()

        asyncio.run(_run())

    def test_diagram_kind_exception_logs_warning(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[
                "sequenceDiagram\n    A->>B: ok\n    B-->>A: done",
                RuntimeError("simulated LLM failure"),
            ]
        )

        def _two_kinds(_self, _pd, _pt):
            return [DiagramType.SEQUENCE_DIAGRAM, DiagramType.STATE]

        async def _run():
            with patch("wiki.semantic_diagram_gen.log") as mock_log:
                with patch.object(SemanticDiagramGenerator, "decide_diagram_types", _two_kinds):
                    gen = SemanticDiagramGenerator(llm=mock_llm)
                    pd = _make_page_data(edges=_make_edges(5))
                    await gen.generate_for_page(pd, PageType.MODULE_OVERVIEW, "digest", "full")
                events = [c.args[0] for c in mock_log.warning.call_args_list if c.args]
                assert "semantic_diagram_kind_failed" in events
                mock_log.debug.assert_not_called()

        asyncio.run(_run())

    def test_topic_full_mode_generates_sequence_diagram(self):
        """P0-4: TOPIC pages must not be skipped; LLM path returns diagrams when mermaid is valid."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value="sequenceDiagram\n    A->>B: step\n    B-->>A: done"
        )

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=[])
            diagrams = await gen.generate_for_page(
                pd, PageType.TOPIC, "topic digest", "full"
            )
            assert len(diagrams) >= 1
            assert diagrams[0].diagram_type == DiagramType.SEQUENCE_DIAGRAM
            mock_llm.generate.assert_called()

        asyncio.run(_run())
