"""Tests for wiki content depth enhancements (diagram wiring, template, digest)."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.composer import (
    WikiComposer,
    _STRUCTURED_SECTIONS_CLASS,
    _STRUCTURED_SECTIONS_FUNCTION,
    _STRUCTURED_SECTIONS_MODULE,
)
from wiki.data_collector import PageData
from wiki.models import DiagramType, PageType, SourceLocation, WikiDiagram


def _loc(file_path: str, start: int, end: int, fqn: str) -> SourceLocation:
    return SourceLocation(
        file_path=file_path,
        start_line=start,
        end_line=end,
        fqn=fqn,
        repository="demo",
    )


def _make_module_page_data() -> PageData:
    """Module-level PageData with edges suitable for diagram generation."""
    node = GraphNode(
        label=NodeLabel.MODULE,
        uid="mod-1",
        properties={"name": "auth", "path": "src/auth"},
    )
    child_a = GraphNode(label=NodeLabel.CLASS, uid="cls-1", properties={"name": "AuthService"})
    child_b = GraphNode(label=NodeLabel.CLASS, uid="cls-2", properties={"name": "TokenManager"})
    edges = [
        GraphEdge(source_uid="mod-1", target_uid="cls-1", edge_type=EdgeType.CONTAINS, properties={}),
        GraphEdge(source_uid="mod-1", target_uid="cls-2", edge_type=EdgeType.CONTAINS, properties={}),
        GraphEdge(source_uid="cls-1", target_uid="cls-2", edge_type=EdgeType.CALLS, properties={}),
    ]
    return PageData(
        node=node,
        edges=edges,
        children=[child_a, child_b],
        source_location=_loc("src/auth/__init__.py", 1, 1, "auth"),
        method_locations=[],
        business_summary=None,
        methods=[],
    )


def _make_class_page_data() -> PageData:
    """Class-level PageData with CALLS edges for call flowchart."""
    node = GraphNode(
        label=NodeLabel.CLASS,
        uid="cls-1",
        properties={"name": "AuthService", "path": "src/auth/service.py"},
    )
    method_a = GraphNode(label=NodeLabel.FUNCTION, uid="fn-1", properties={"name": "login"})
    edges = [
        GraphEdge(source_uid="cls-1", target_uid="fn-1", edge_type=EdgeType.CONTAINS, properties={}),
        GraphEdge(source_uid="fn-1", target_uid="cls-1", edge_type=EdgeType.CALLS, properties={}),
    ]
    return PageData(
        node=node,
        edges=edges,
        children=[],
        source_location=_loc("src/auth/service.py", 1, 50, "AuthService"),
        method_locations=[],
        business_summary=None,
        methods=[method_a],
    )


class TestBuildDiagramsEnhanced:
    """Tests for _build_diagrams with additional diagram generators."""

    def test_module_returns_multiple_diagram_types(self) -> None:
        composer = WikiComposer(llm=None, context_builder=MagicMock())
        page_data = _make_module_page_data()
        diagrams = composer._build_diagrams(page_data, PageType.MODULE_OVERVIEW)

        assert len(diagrams) >= 2, f"Expected >=2 diagrams for module, got {len(diagrams)}"
        titles = {d.title for d in diagrams}
        assert "Dependency graph" in titles

    def test_class_returns_data_flow_diagram(self) -> None:
        composer = WikiComposer(llm=None, context_builder=MagicMock())
        page_data = _make_class_page_data()
        diagrams = composer._build_diagrams(page_data, PageType.CLASS_DETAIL)

        titles = {d.title for d in diagrams}
        assert "Class diagram" in titles

    def test_diagram_generator_failure_does_not_crash(self) -> None:
        composer = WikiComposer(llm=None, context_builder=MagicMock())
        page_data = _make_module_page_data()
        with patch("wiki.composer.generate_layered_architecture_diagram", side_effect=RuntimeError("boom")):
            diagrams = composer._build_diagrams(page_data, PageType.MODULE_OVERVIEW)
        assert len(diagrams) >= 1, "Should still return dependency graph even if architecture diagram fails"

    def test_empty_diagram_not_added(self) -> None:
        composer = WikiComposer(llm=None, context_builder=MagicMock())
        empty_diagram = WikiDiagram(
            diagram_type=DiagramType.FLOWCHART,
            content="graph TD\n",
            title="Empty",
        )
        page_data = _make_module_page_data()
        with patch("wiki.composer.generate_layered_architecture_diagram", return_value=empty_diagram):
            diagrams = composer._build_diagrams(page_data, PageType.MODULE_OVERVIEW)
        titles = {d.title for d in diagrams}
        assert "Architecture layers" not in titles, "Empty diagram should be filtered out"


class TestStructuredSectionTemplates:
    """Tests for LLM structured section templates and tier-2 system prompt."""

    def test_module_template_includes_how_it_works(self) -> None:
        assert "How it Works" in _STRUCTURED_SECTIONS_MODULE

    def test_class_template_includes_how_it_works(self) -> None:
        assert "How it Works" in _STRUCTURED_SECTIONS_CLASS

    def test_module_template_includes_mermaid_guidance(self) -> None:
        assert "mermaid" in _STRUCTURED_SECTIONS_MODULE.lower()

    def test_function_template_includes_calling_patterns(self) -> None:
        assert "calling patterns" in _STRUCTURED_SECTIONS_FUNCTION.lower()

    def test_system_prompt_mentions_mermaid(self) -> None:
        source = inspect.getsource(WikiComposer._tier2_llm)
        assert "mermaid" in source.lower()
