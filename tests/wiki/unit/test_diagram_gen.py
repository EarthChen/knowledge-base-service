"""Tests for wiki/diagram_gen.py — T1.2 DiagramGen (Mermaid)."""

from __future__ import annotations

import re

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.diagram_gen import (
    generate_call_flowchart,
    generate_class_diagram,
    generate_dependency_graph,
)
from wiki.models import DiagramType


def _fn(name: str, line: int, path: str = "src/x.py") -> GraphNode:
    return GraphNode(
        label=NodeLabel.FUNCTION,
        properties={"name": name, "file": path, "start_line": line},
    )


def _cls(name: str, line: int = 1, path: str = "src/C.java") -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS,
        properties={"name": name, "file": path, "start_line": line},
    )


def _mod(name: str, path: str = "src/mod.py", line: int = 1) -> GraphNode:
    return GraphNode(
        label=NodeLabel.MODULE,
        properties={"name": name, "file": path, "start_line": line},
    )


class TestClassDiagram:
    def test_class_diagram_simple(self):
        """Class with 3 methods, no inheritance → valid classDiagram."""
        cls_node = _cls("Demo")
        m1, m2, m3 = _fn("a", 10), _fn("b", 20), _fn("c", 30)
        edges = [
            GraphEdge(EdgeType.CONTAINS, cls_node.uid, m1.uid),
            GraphEdge(EdgeType.CONTAINS, cls_node.uid, m2.uid),
            GraphEdge(EdgeType.CONTAINS, cls_node.uid, m3.uid),
        ]
        out = generate_class_diagram(cls_node, edges)
        assert out.diagram_type == DiagramType.CLASS_DIAGRAM
        assert out.content.startswith("classDiagram")
        assert "Demo" in out.content
        for name in ("a", "b", "c"):
            assert name in out.content

    def test_class_diagram_inheritance(self):
        """Class extending 2 parents → <|-- arrows for each parent."""
        child = _cls("Child", 5)
        p1, p2 = _cls("ParentOne", 1), _cls("ParentTwo", 2)
        edges = [
            GraphEdge(EdgeType.INHERITS, child.uid, p1.uid),
            GraphEdge(EdgeType.INHERITS, child.uid, p2.uid),
        ]
        out = generate_class_diagram(child, edges)
        assert "<|--" in out.content
        assert "ParentOne" in out.content and "ParentTwo" in out.content
        assert "Child" in out.content

    def test_class_diagram_deep_chain(self):
        """4-level inheritance → all levels connected."""
        a, b, c, d = _cls("A", 1), _cls("B", 2), _cls("C", 3), _cls("D", 4)
        edges = [
            GraphEdge(EdgeType.INHERITS, b.uid, a.uid),
            GraphEdge(EdgeType.INHERITS, c.uid, b.uid),
            GraphEdge(EdgeType.INHERITS, d.uid, c.uid),
        ]
        out = generate_class_diagram(d, edges)
        content = out.content.replace(" ", "").replace("\n", "")
        assert "<|--" in content
        assert "A<|--B" in content
        assert "B<|--C" in content
        assert "C<|--D" in content

    def test_class_diagram_many_methods(self):
        """Class with 50 methods → methods listed."""
        cls_node = _cls("Mega")
        edges = []
        for i in range(50):
            fn = _fn(f"m{i}", 100 + i)
            edges.append(GraphEdge(EdgeType.CONTAINS, cls_node.uid, fn.uid))
        out = generate_class_diagram(cls_node, edges)
        for i in range(50):
            assert f"m{i}" in out.content

    def test_diagram_complexity_limit_class_inheritance(self):
        """>15 distinct class nodes in inheritance → truncated with ... and N more."""
        focal = _cls("Focal", 0)
        parents = [_cls(f"P{i}", i + 1) for i in range(20)]
        edges = [GraphEdge(EdgeType.INHERITS, focal.uid, p.uid) for p in parents]
        out = generate_class_diagram(focal, edges)
        assert "... and " in out.content and "more" in out.content
        match = re.search(r"\.\.\.\s+and\s+(\d+)\s+more", out.content)
        assert match is not None
        collapsed = int(match.group(1))
        assert collapsed >= 1


class TestDependencyGraph:
    def test_dependency_graph_basic(self):
        """Module with 5 imports → flowchart with arrows."""
        m = _mod("Main", "src/main.py")
        imports = [_mod(f"d{i}", f"src/d{i}.py") for i in range(5)]
        edges = [GraphEdge(EdgeType.IMPORTS, m.uid, imp.uid) for imp in imports]
        out = generate_dependency_graph(m, edges)
        assert out.diagram_type == DiagramType.DEPENDENCY_GRAPH
        assert out.content.startswith("flowchart")
        assert "-->" in out.content
        for imp in imports:
            assert imp.properties["name"] in out.content or str(imp.properties["name"]) in out.content

    def test_dependency_graph_circular(self):
        """Modules A→B→C→A → all edges shown, no infinite loop."""
        ma, mb, mc = _mod("A", "a.py"), _mod("B", "b.py"), _mod("C", "c.py")
        edges = [
            GraphEdge(EdgeType.IMPORTS, ma.uid, mb.uid),
            GraphEdge(EdgeType.IMPORTS, mb.uid, mc.uid),
            GraphEdge(EdgeType.IMPORTS, mc.uid, ma.uid),
        ]
        out = generate_dependency_graph(ma, edges)
        assert "-->" in out.content
        edge_count = out.content.count("-->")
        assert edge_count == 3


class TestCallFlowchart:
    def test_call_flowchart_linear(self):
        """A→B→C call chain → linear flowchart."""
        a, b, c = _fn("a", 1), _fn("b", 2), _fn("c", 3)
        edges = [
            GraphEdge(EdgeType.CALLS, a.uid, b.uid),
            GraphEdge(EdgeType.CALLS, b.uid, c.uid),
        ]
        out = generate_call_flowchart(a, edges)
        assert out.diagram_type == DiagramType.FLOWCHART
        assert out.content.startswith("flowchart")
        assert out.content.count("-->") >= 2

    def test_call_flowchart_branching(self):
        """A→B, A→C → branching shown."""
        a, b, c = _fn("entry", 1), _fn("left", 2), _fn("right", 3)
        edges = [
            GraphEdge(EdgeType.CALLS, a.uid, b.uid),
            GraphEdge(EdgeType.CALLS, a.uid, c.uid),
        ]
        out = generate_call_flowchart(a, edges)
        assert out.content.count("-->") >= 2
        assert "entry" in out.content


class TestDiagramEdgeCases:
    def test_empty_edges(self):
        """No edges → minimal valid diagram."""
        cls_node = _cls("Lonely")
        out_cls = generate_class_diagram(cls_node, [])
        assert out_cls.diagram_type == DiagramType.CLASS_DIAGRAM
        assert out_cls.content.startswith("classDiagram")

        mod = _mod("solo", "solo.py")
        out_dep = generate_dependency_graph(mod, [])
        assert out_dep.diagram_type == DiagramType.DEPENDENCY_GRAPH
        assert bool(out_dep.content.strip())

        fn = _fn("main", 1)
        out_call = generate_call_flowchart(fn, [])
        assert out_call.diagram_type == DiagramType.FLOWCHART
        assert bool(out_call.content.strip())

    def test_mermaid_syntax_valid(self):
        """Any diagram → starts with correct Mermaid keyword (no broken arrow-only output)."""
        cls_node = _cls("X")
        d1 = generate_class_diagram(cls_node, [])
        assert d1.content.startswith("classDiagram")

        mod = _mod("M", "m.py")
        d2 = generate_dependency_graph(mod, [])
        assert d2.content.startswith("flowchart")

        fn = _fn("f", 1)
        d3 = generate_call_flowchart(fn, [])
        assert d3.content.startswith("flowchart")
        assert not re.match(r"^\s*--+>\s*$", d3.content)

    def test_special_chars_escaped(self):
        """Node name with <, >, & → escaped in output."""
        raw_name = 'Bad<X>&Item'
        fn = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={"name": raw_name, "file": "f.py", "start_line": 1},
            uid='Function:f.py:Bad<X>&Item:1',
        )
        out = generate_call_flowchart(fn, [])
        assert "&lt;" in out.content
        assert "&gt;" in out.content
        assert "&amp;" in out.content

    def test_diagram_complexity_limit(self):
        """>15 nodes → truncated with ... and N more."""
        entry = _fn("root", 1)
        others = [_fn(f"n{i}", i + 2) for i in range(18)]
        edges = [GraphEdge(EdgeType.CALLS, entry.uid, o.uid) for o in others]
        out = generate_call_flowchart(entry, edges)
        assert "... and " in out.content and "more" in out.content

