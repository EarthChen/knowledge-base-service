from __future__ import annotations

from wiki.topo_sort import kahn_topological_order
from wiki.tour import TourPage, TourStep, GuidedTour, assign_page_layers, build_tour


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


class TestTourDataModel:
    def test_tour_page(self):
        tp = TourPage(path="domain/page.md", title="Page", reading_order=1, architecture_layer="api")
        assert tp.reading_order == 1

    def test_tour_step(self):
        tp = TourPage(path="a.md", title="A", reading_order=1, architecture_layer="api")
        ts = TourStep(order=1, layer_name="api", layer_display="API 入口层", pages=[tp])
        assert len(ts.pages) == 1

    def test_guided_tour_to_dict(self):
        tp = TourPage(path="a.md", title="A", reading_order=1, architecture_layer="api")
        ts = TourStep(order=1, layer_name="api", layer_display="API", pages=[tp])
        tour = GuidedTour(total_pages=1, steps=[ts])
        d = tour.to_dict()
        assert d["total_pages"] == 1
        assert len(d["steps"]) == 1
        assert d["steps"][0]["pages"][0]["path"] == "a.md"


class TestTourBuilder:
    def test_assign_page_layers_majority_vote(self):
        pages = [
            {"path": "a.md", "covered_entity_uids": ["mod1.func1", "mod1.func2"]},
            {"path": "b.md", "covered_entity_uids": ["mod2.func1"]},
        ]
        arch_layers = {"mod1": {"layer": "api", "confidence": 0.9}, "mod2": {"layer": "data", "confidence": 0.8}}
        entity_to_module = {"mod1.func1": "mod1", "mod1.func2": "mod1", "mod2.func1": "mod2"}
        result = assign_page_layers(pages, arch_layers, entity_to_module)
        assert result["a.md"] == "api"
        assert result["b.md"] == "data"

    def test_assign_page_layers_fallback_unknown(self):
        pages = [{"path": "c.md", "covered_entity_uids": ["orphan"]}]
        result = assign_page_layers(pages, {}, {})
        assert result["c.md"] == "unknown"

    def test_build_tour_groups_by_layer(self):
        topo_order = ["a.md", "b.md", "c.md"]
        page_layers = {"a.md": "api", "b.md": "service", "c.md": "data"}
        pages = [
            {"path": "a.md", "title": "A"},
            {"path": "b.md", "title": "B"},
            {"path": "c.md", "title": "C"},
        ]
        tour = build_tour(topo_order, page_layers, pages)
        assert tour.total_pages == 3
        assert tour.steps[0].layer_name == "api"
        assert tour.steps[1].layer_name == "service"
        assert tour.steps[2].layer_name == "data"
        assert tour.steps[0].pages[0].reading_order == 1
        assert tour.steps[2].pages[0].reading_order == 3

    def test_build_tour_empty_pages(self):
        tour = build_tour([], {}, [])
        assert tour.total_pages == 0
        assert tour.steps == []
