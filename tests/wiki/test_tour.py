from __future__ import annotations

from wiki.topo_sort import kahn_topological_order


class TestKahnTopologicalOrder:
    def test_empty_graph(self):
        assert kahn_topological_order({}) == []

    def test_single_node(self):
        assert kahn_topological_order({"A": []}) == ["A"]

    def test_linear_chain(self):
        edges = {"A": ["B"], "B": ["C"]}
        result = kahn_topological_order(edges)
        assert result.index("A") < result.index("B")
        assert result.index("B") < result.index("C")

    def test_diamond_dag(self):
        edges = {"A": ["B", "C"], "B": ["D"], "C": ["D"]}
        result = kahn_topological_order(edges)
        assert result[0] == "A"
        assert result[-1] == "D"

    def test_roots_first(self):
        """Kahn returns roots first (opposite of Tarjan leaves-first)."""
        edges = {"root": ["mid"], "mid": ["leaf"]}
        result = kahn_topological_order(edges)
        assert result == ["root", "mid", "leaf"]

    def test_cycle_broken(self):
        edges = {"A": ["B"], "B": ["C"], "C": ["A"]}
        result = kahn_topological_order(edges)
        assert set(result) == {"A", "B", "C"}
        assert len(result) == 3

    def test_multiple_roots(self):
        edges = {"A": ["C"], "B": ["C"]}
        result = kahn_topological_order(edges)
        assert result[-1] == "C"
        assert set(result[:2]) == {"A", "B"}

    def test_disconnected_components(self):
        edges = {"A": ["B"], "C": ["D"]}
        result = kahn_topological_order(edges)
        assert len(result) == 4
        assert result.index("A") < result.index("B")
        assert result.index("C") < result.index("D")
