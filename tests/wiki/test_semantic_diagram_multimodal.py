"""Multimodal semantic diagram generation (state, flowchart, architecture)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.data_collector import PageData
from wiki.models import DiagramType, PageType, SourceLocation
from wiki.semantic_diagram_gen import SemanticDiagramGenerator


def _make_node(
    label: NodeLabel = NodeLabel.CLASS,
    uid: str = "test:cls:Stateful",
    *,
    name: str = "StatefulSvc",
) -> GraphNode:
    return GraphNode(uid=uid, label=label, properties={"name": name})


def _method_node(name: str, **extra: str) -> GraphNode:
    props: dict[str, str | list[str]] = {"name": name}
    props.update(extra)
    return GraphNode(uid=f"test:fn:{name}", label=NodeLabel.FUNCTION, properties=props)


def _make_page_data(
    *,
    node: GraphNode | None = None,
    edges: list[GraphEdge] | None = None,
    methods: list[GraphNode] | None = None,
    children: list[GraphNode] | None = None,
) -> PageData:
    n = node or _make_node()
    loc = SourceLocation(file_path="x.py", start_line=1, end_line=10, fqn="x", repository="r")
    return PageData(
        node=n,
        edges=edges or [],
        children=children or [],
        source_location=loc,
        method_locations=[],
        business_summary=None,
        methods=methods or [],
    )


def _calls_edges(count: int, source_uid: str = "test:mod:main") -> list[GraphEdge]:
    return [
        GraphEdge(
            source_uid=source_uid,
            target_uid=f"test:mod:dep{i}",
            edge_type=EdgeType.CALLS,
            properties={},
        )
        for i in range(count)
    ]


class TestDecideDiagramTypes:
    def test_decide_diagram_types_stateful_entity(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(
            methods=[_method_node("updateStatus"), _method_node("run")],
        )
        types = gen.decide_diagram_types(pd, PageType.CLASS_DETAIL)
        assert DiagramType.SEQUENCE_DIAGRAM in types
        assert DiagramType.STATE in types

    def test_decide_diagram_types_dataflow_entity(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(
            methods=[_method_node("transformPayload"), _method_node("save")],
        )
        types = gen.decide_diagram_types(pd, PageType.CLASS_DETAIL)
        assert DiagramType.SEQUENCE_DIAGRAM in types
        assert DiagramType.DATA_FLOW in types

    def test_decide_diagram_types_domain_overview(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(node=_make_node(NodeLabel.MODULE, "test:mod:d"))
        for pt in (PageType.DOMAIN_OVERVIEW, PageType.REPO_OVERVIEW):
            types = gen.decide_diagram_types(pd, pt)
            assert DiagramType.SEQUENCE_DIAGRAM in types
            assert DiagramType.ARCHITECTURE in types

    def test_decide_diagram_types_simple_entity(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(
            node=_make_node(name="PlainSvc"),
            methods=[_method_node("foo"), _method_node("bar")],
        )
        types = gen.decide_diagram_types(pd, PageType.CLASS_DETAIL)
        assert types == [DiagramType.SEQUENCE_DIAGRAM]


class TestMultimodalGeneration:
    def test_generate_state_diagram(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value="```mermaid\nstateDiagram-v2\n    [*] --> Idle\n    Idle --> Active\n```"
        )

        async def _run():
            from wiki import semantic_diagram_gen as sdg

            gen = SemanticDiagramGenerator(llm=mock_llm)
            d = await gen.generate_state_diagram("OrderSvc", "digest", mock_llm)
            assert d is not None
            assert d.diagram_type == DiagramType.STATE
            assert d.content.startswith("stateDiagram-v2")
            mock_llm.generate.assert_called_once()
            assert mock_llm.generate.call_args.kwargs.get("system") == sdg._SYSTEM_PROMPT

        asyncio.run(_run())

    def test_generate_dataflow_diagram(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="flowchart LR\n    A --> B\n    B --> C")

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            d = await gen.generate_dataflow_diagram("Pipe", "digest", mock_llm)
            assert d is not None
            assert d.diagram_type == DiagramType.DATA_FLOW
            assert d.content.startswith("flowchart")

        asyncio.run(_run())

    def test_generate_architecture_diagram(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="graph TD\n    API --> SVC\n    SVC --> DB")

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            d = await gen.generate_architecture_diagram("Platform", "digest", mock_llm)
            assert d is not None
            assert d.diagram_type == DiagramType.ARCHITECTURE
            assert d.content.startswith("graph")

        asyncio.run(_run())

    def test_sanitize_mermaid_output(self):
        raw = "```mermaid\nstateDiagram-v2\n    [*] --> X\n```"
        out = SemanticDiagramGenerator.sanitize_mermaid_output(raw)
        assert out is not None
        assert out.startswith("stateDiagram-v2")
        assert "```" not in out

        bad = "just prose"
        assert SemanticDiagramGenerator.sanitize_mermaid_output(bad) is None

    def test_generate_for_page_multimodal(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[
                "sequenceDiagram\n    A->>B: x\n    B-->>A: y",
                "stateDiagram-v2\n    [*] --> S1",
                "flowchart TD\n    IN --> OUT",
            ]
        )

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            methods = [
                _method_node("setState"),
                _method_node("transform"),
                *[_method_node(f"helper{i}") for i in range(4)],
            ]
            pd = _make_page_data(
                node=_make_node(NodeLabel.CLASS, "test:cls:Big"),
                edges=_calls_edges(3, "test:cls:Big"),
                methods=methods,
            )
            digest = "class Big with setState and transform pipeline"
            diagrams = await gen.generate_for_page(pd, PageType.CLASS_DETAIL, digest, "full")
            assert len(diagrams) == 3
            kinds = [d.diagram_type for d in diagrams]
            assert DiagramType.SEQUENCE_DIAGRAM in kinds
            assert DiagramType.STATE in kinds
            assert DiagramType.DATA_FLOW in kinds
            assert mock_llm.generate.call_count == 3

        asyncio.run(_run())


def test_generate_for_page_multimodal_uses_system_prompt():
    """Assert every LLM call passes _SYSTEM_PROMPT (explicit check without importorskip quirks)."""
    from wiki import semantic_diagram_gen as sdg

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        side_effect=[
            "sequenceDiagram\n    A->>B: x\n    B-->>A: y",
            "stateDiagram-v2\n    [*] --> S1",
            "flowchart TD\n    IN --> OUT",
        ]
    )

    async def _run():
        gen = SemanticDiagramGenerator(llm=mock_llm)
        methods = [
            _method_node("setState"),
            _method_node("transform"),
            *[_method_node(f"helper{i}") for i in range(4)],
        ]
        pd = _make_page_data(
            node=_make_node(NodeLabel.CLASS, "test:cls:Big"),
            edges=_calls_edges(3, "test:cls:Big"),
            methods=methods,
        )
        await gen.generate_for_page(pd, PageType.CLASS_DETAIL, "digest", "full")
        for call in mock_llm.generate.call_args_list:
            kwargs = call.kwargs
            assert kwargs.get("system") == sdg._SYSTEM_PROMPT

    asyncio.run(_run())
