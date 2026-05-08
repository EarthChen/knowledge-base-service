# tests/wiki/test_topo_sort.py
from wiki.topo_sort import topological_order


class TestTopologicalOrder:
    def test_simple_chain(self):
        """A -> B -> C should produce [C, B, A] or [A, B, C] depending on direction."""
        edges = {"A": ["B"], "B": ["C"], "C": []}
        order = topological_order(edges)
        assert order.index("C") < order.index("B") < order.index("A")

    def test_no_edges(self):
        """Isolated nodes should all appear."""
        edges = {"A": [], "B": [], "C": []}
        order = topological_order(edges)
        assert set(order) == {"A", "B", "C"}

    def test_cycle_detected_as_scc(self):
        """A -> B -> A forms a cycle; both should appear grouped."""
        edges = {"A": ["B"], "B": ["A"], "C": []}
        order = topological_order(edges)
        assert len(order) == 3
        assert "C" in order
        assert "A" in order
        assert "B" in order

    def test_diamond_dependency(self):
        """A -> B, A -> C, B -> D, C -> D should have D first."""
        edges = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        order = topological_order(edges)
        assert order.index("D") < order.index("A")

    def test_empty_graph(self):
        assert topological_order({}) == []

    def test_single_node(self):
        assert topological_order({"X": []}) == ["X"]
