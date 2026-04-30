"""Integration tests: composer + semantic diagram generation.

Verifies that SemanticDiagramGenerator is properly wired into WikiComposer
and that diagrams flow through compose_page correctly.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.models import DiagramType, PageType, WikiConfig, WikiDiagram
from wiki.semantic_diagram_gen import SemanticDiagramGenerator


class TestComposerHasSemanticGenerator:
    def test_composer_init_creates_semantic_gen(self):
        from wiki.composer import WikiComposer

        mock_llm = MagicMock()
        ctx = MagicMock()
        composer = WikiComposer(llm=mock_llm, context_builder=ctx)
        assert hasattr(composer, "_semantic_gen")
        assert isinstance(composer._semantic_gen, SemanticDiagramGenerator)

    def test_composer_init_without_llm(self):
        from wiki.composer import WikiComposer

        ctx = MagicMock()
        composer = WikiComposer(llm=None, context_builder=ctx)
        assert composer._semantic_gen._llm is None


class TestSemanticDiagramsInComposePage:
    """Patch SemanticDiagramGenerator at class level to verify compose_page integration."""

    def test_semantic_diagrams_appended_in_full_mode(self):
        fake_diagram = WikiDiagram(
            diagram_type=DiagramType.SEQUENCE_DIAGRAM,
            content="sequenceDiagram\n    A->>B: call",
            title="Module interaction flow",
        )

        async def _run():
            from wiki.composer import WikiComposer

            mock_llm = AsyncMock()
            mock_llm.generate = AsyncMock(return_value="tier2 content")
            ctx = MagicMock()
            ctx.build_style_sheet.return_value = ""
            ctx.build_page_context.return_value = ""
            ctx.find_related_docs = AsyncMock(return_value=[])

            with patch.object(
                SemanticDiagramGenerator, "generate", new_callable=AsyncMock, return_value=[fake_diagram]
            ) as mock_gen:
                composer = WikiComposer(llm=mock_llm, context_builder=ctx)

                node = GraphNode(
                    uid="test:mod:main",
                    label=NodeLabel.MODULE,
                    properties={"name": "main"},
                )
                edges = [
                    GraphEdge(
                        source_uid="test:mod:main",
                        target_uid=f"test:mod:dep{i}",
                        edge_type=EdgeType.CALLS,
                        properties={},
                    )
                    for i in range(5)
                ]
                pd = MagicMock()
                pd.node = node
                pd.edges = edges
                pd.children = []
                pd.methods = []
                pd.code_snippets = []
                pd.related_chunks = []
                pd.method_locations = []
                pd.source_location = MagicMock()

                config = WikiConfig(repository="test/repo", mode="full", language="en")
                page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, config)

                assert page is not None
                mock_gen.assert_called_once()
                call_args = mock_gen.call_args
                assert call_args[0][1] == PageType.MODULE_OVERVIEW
                assert call_args[0][3] == "full"

                seq_diagrams = [
                    d for d in page.diagrams
                    if d.diagram_type == DiagramType.SEQUENCE_DIAGRAM
                ]
                assert len(seq_diagrams) == 1
                assert seq_diagrams[0].content == "sequenceDiagram\n    A->>B: call"

        asyncio.run(_run())

    def test_semantic_gen_skipped_in_structure_mode(self):
        """In structure mode, _should_generate returns False so generate is never called."""

        async def _run():
            from wiki.composer import WikiComposer

            mock_llm = AsyncMock()
            ctx = MagicMock()
            ctx.build_style_sheet.return_value = ""
            ctx.build_page_context.return_value = ""

            with patch.object(
                SemanticDiagramGenerator, "generate", new_callable=AsyncMock, return_value=[]
            ) as mock_gen:
                composer = WikiComposer(llm=mock_llm, context_builder=ctx)

                node = GraphNode(
                    uid="test:mod:main",
                    label=NodeLabel.MODULE,
                    properties={"name": "main", "business_summary": "A module"},
                )
                pd = MagicMock()
                pd.node = node
                pd.edges = []
                pd.children = []
                pd.methods = []
                pd.code_snippets = []
                pd.related_chunks = []
                pd.method_locations = []
                pd.source_location = MagicMock()
                pd.business_summary = "A module summary"

                config = WikiConfig(repository="test/repo", mode="structure", language="en")
                page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, config)

                assert page is not None
                mock_gen.assert_not_called()

                seq_diagrams = [
                    d for d in page.diagrams
                    if d.diagram_type == DiagramType.SEQUENCE_DIAGRAM
                ]
                assert len(seq_diagrams) == 0

        asyncio.run(_run())

    def test_compose_page_succeeds_when_semantic_gen_returns_empty(self):
        """compose_page completes normally when semantic gen returns no diagrams."""

        async def _run():
            from wiki.composer import WikiComposer

            mock_llm = AsyncMock()
            mock_llm.generate = AsyncMock(return_value="tier2 content")
            ctx = MagicMock()
            ctx.build_style_sheet.return_value = ""
            ctx.build_page_context.return_value = ""
            ctx.find_related_docs = AsyncMock(return_value=[])

            with patch.object(
                SemanticDiagramGenerator, "generate", new_callable=AsyncMock, return_value=[]
            ), patch.object(
                SemanticDiagramGenerator, "_should_generate", return_value=False
            ):
                composer = WikiComposer(llm=mock_llm, context_builder=ctx)

                node = GraphNode(
                    uid="test:mod:main",
                    label=NodeLabel.MODULE,
                    properties={"name": "main"},
                )
                pd = MagicMock()
                pd.node = node
                pd.edges = []
                pd.children = []
                pd.methods = []
                pd.code_snippets = []
                pd.related_chunks = []
                pd.method_locations = []
                pd.source_location = MagicMock()

                config = WikiConfig(repository="test/repo", mode="full", language="en")
                page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, config)
                assert page is not None
                seq_diagrams = [
                    d for d in page.diagrams
                    if d.diagram_type == DiagramType.SEQUENCE_DIAGRAM
                ]
                assert len(seq_diagrams) == 0

        asyncio.run(_run())
