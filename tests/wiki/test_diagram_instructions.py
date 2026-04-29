"""tests/wiki/test_diagram_instructions.py — Sprint 3 tests for LLM semantic diagram instructions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from store.schema import GraphNode, NodeLabel


def _stub_methods(count: int) -> list[GraphNode]:
    """Method nodes must expose .properties / .uid like PageData.methods."""
    return [
        GraphNode(
            uid=f"fn:stub:{i}",
            label=NodeLabel.FUNCTION,
            properties={"name": f"method_{i}"},
        )
        for i in range(count)
    ]


@dataclass
class FakePageData:
    node: Any
    edges: list = field(default_factory=list)
    children: list = field(default_factory=list)
    methods: list = field(default_factory=list)
    code_snippets: list = field(default_factory=list)
    related_chunks: list = field(default_factory=list)


class TestDiagramInstructions:
    def test_entry_point_gets_sequence_diagram_instruction(self) -> None:
        """Entry point entities should get Mermaid sequence diagram instructions."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(
            uid="ep_uid",
            label=NodeLabel.CLASS,
            properties={
                "name": "UserController",
                "path": "controller.py",
                "is_entry_point": True,
            },
        )
        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
        assert "Diagram Requirement" in digest
        assert "sequence diagram" in digest.lower()

    def test_module_gets_flowchart_instruction(self) -> None:
        """Module entities should get Mermaid flowchart instructions."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(
            uid="mod_uid",
            label=NodeLabel.MODULE,
            properties={
                "name": "UserModule",
                "path": "user_module.py",
            },
        )
        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.MODULE_OVERVIEW)
        assert "Diagram Requirement" in digest
        assert "flowchart" in digest.lower()

    def test_small_class_no_diagram_instruction(self) -> None:
        """Classes with few methods should NOT get diagram instructions."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(
            uid="small_uid",
            label=NodeLabel.CLASS,
            properties={
                "name": "SmallClass",
                "path": "small.py",
                "is_entry_point": False,
            },
        )
        page_data = FakePageData(node=node, methods=_stub_methods(3))
        digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
        assert "Diagram Requirement" not in digest

    def test_large_class_gets_diagram_instruction(self) -> None:
        """Classes with many methods should get sequence diagram instructions."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(
            uid="large_uid",
            label=NodeLabel.CLASS,
            properties={
                "name": "LargeService",
                "path": "large.py",
                "is_entry_point": False,
            },
        )
        page_data = FakePageData(node=node, methods=_stub_methods(8))
        digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
        assert "Diagram Requirement" in digest

    def test_function_no_diagram(self) -> None:
        """Function entities should NOT get diagram instructions."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(
            uid="func_uid",
            label=NodeLabel.FUNCTION,
            properties={
                "name": "process_data",
                "path": "utils.py",
            },
        )
        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
        assert "Diagram Requirement" not in digest

    def test_entry_point_overrides_module(self) -> None:
        """Entry point flag should trigger sequence diagram even for MODULE_OVERVIEW."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(
            uid="ep_mod_uid",
            label=NodeLabel.MODULE,
            properties={
                "name": "ApiGateway",
                "path": "gateway.py",
                "is_entry_point": True,
            },
        )
        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.MODULE_OVERVIEW)
        assert "Diagram Requirement" in digest
        assert "sequence diagram" in digest.lower()
