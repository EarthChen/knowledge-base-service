"""Tests for wiki.entity_filter — EntityStrategy classification."""

from __future__ import annotations

from store.schema import GraphNode, NodeLabel
from wiki.dependency_graph import ModuleEdge, ModuleGraph, ModuleInfo
from wiki.entity_filter import WikiEntityFilter
from wiki.models import EntityStrategy


def _filter() -> WikiEntityFilter:
    return WikiEntityFilter()


class TestWikiEntityFilter:
    """Classify entities into FULL_PAGE, STANDARD_PAGE, MERGE_TO_PARENT."""

    def test_enum_like_class_small_no_methods_merges(self) -> None:
        tiny = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "Color",
                "fqn": "pkg.Color",
                "file": "pkg/Enums.kt",
                "start_line": 1,
                "end_line": 10,
                "methods_count": 0,
                "is_interface": False,
                "semantic_roles": [],
            },
            uid="cls-enum-like",
        )
        assert (
            _filter().classify(tiny, edge_count=0, children_count=0)
            == EntityStrategy.MERGE_TO_PARENT
        )

    def test_trivial_function_merges(self) -> None:
        trivial = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={
                "name": "x",
                "file": "f.py",
                "start_line": 1,
                "end_line": 3,
            },
            uid="fn-trivial",
        )
        assert (
            _filter().classify(trivial, edge_count=0, children_count=0)
            == EntityStrategy.MERGE_TO_PARENT
        )

    def test_normal_service_class_ten_methods_standard(self) -> None:
        svc = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "UserService",
                "fqn": "app.UserService",
                "file": "app/UserService.java",
                "start_line": 10,
                "end_line": 200,
                "methods_count": 10,
                "is_interface": False,
                "semantic_roles": [],
            },
            uid="cls-service",
        )
        assert (
            _filter().classify(svc, edge_count=3, children_count=0) == EntityStrategy.STANDARD_PAGE
        )

    def test_controller_role_full_page(self) -> None:
        ctrl = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "OrderController",
                "fqn": "api.OrderController",
                "file": "api/OrderController.java",
                "start_line": 1,
                "end_line": 50,
                "methods_count": 2,
                "is_interface": False,
                "semantic_roles": ["http_controller"],
            },
            uid="cls-ctrl",
        )
        assert (
            _filter().classify(ctrl, edge_count=0, children_count=0) == EntityStrategy.FULL_PAGE
        )

    def test_many_edges_full_page(self) -> None:
        heavy = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "Hub",
                "fqn": "app.Hub",
                "file": "app/Hub.java",
                "start_line": 1,
                "end_line": 40,
                "methods_count": 1,
                "is_interface": False,
                "semantic_roles": [],
            },
            uid="cls-hub",
        )
        assert (
            _filter().classify(heavy, edge_count=10, children_count=0) == EntityStrategy.FULL_PAGE
        )


def test_constant_holder_merges() -> None:
    node = GraphNode(
        label=NodeLabel.CLASS,
        properties={
            "name": "Constants",
            "is_interface": False,
            "methods_count": 0,
            "start_line": 1,
            "end_line": 10,
        },
        uid="cls-constants",
    )
    assert (
        _filter().classify(node, edge_count=0, children_count=0)
        == EntityStrategy.MERGE_TO_PARENT
    )


def test_class_with_children_is_standard() -> None:
    node = GraphNode(
        label=NodeLabel.CLASS,
        properties={
            "name": "BaseService",
            "methods_count": 1,
            "start_line": 1,
            "end_line": 30,
        },
        uid="cls-basesvc",
    )
    assert (
        _filter().classify(node, edge_count=0, children_count=3) == EntityStrategy.STANDARD_PAGE
    )


class TestLargeClassStrategy:
    def test_groups_methods_by_annotation(self):
        from wiki.entity_filter import LargeClassStrategy

        methods = [
            GraphNode(
                label=NodeLabel.FUNCTION,
                properties={"name": "createUser", "annotations": ["@PostMapping"]},
            ),
            GraphNode(
                label=NodeLabel.FUNCTION,
                properties={"name": "getUser", "annotations": ["@GetMapping"]},
            ),
            GraphNode(
                label=NodeLabel.FUNCTION,
                properties={"name": "scheduledCleanup", "annotations": ["@Scheduled"]},
            ),
        ] + [GraphNode(label=NodeLabel.FUNCTION, properties={"name": f"helper_{i}"}) for i in range(30)]
        strategy = LargeClassStrategy()
        groups = strategy.group_methods(methods)
        assert len(groups) >= 2
        group_names = [g.name for g in groups]
        assert any("API" in n or "Endpoint" in n for n in group_names)

    def test_below_threshold_returns_single_group(self):
        from wiki.entity_filter import LargeClassStrategy

        methods = [GraphNode(label=NodeLabel.FUNCTION, properties={"name": f"m{i}"}) for i in range(5)]
        strategy = LargeClassStrategy()
        groups = strategy.group_methods(methods)
        assert len(groups) == 1


class TestHubNodeDetector:
    def test_high_degree_detected_as_hub(self):
        from wiki.entity_filter import HubNodeDetector

        modules = [ModuleInfo(name=f"m{i}", path=f"m{i}.py", uid=f"uid_{i}") for i in range(10)]
        edges = [ModuleEdge(source="m0", target=f"m{i}", edge_type="CALLS") for i in range(1, 10)]
        edges += [ModuleEdge(source=f"m{i}", target="m0", edge_type="CALLS") for i in range(1, 10)]
        graph = ModuleGraph(modules=modules, edges=edges, entry_points=[])
        detector = HubNodeDetector()
        hubs = detector.detect_hubs(graph, percentile=90)
        assert "m0" in hubs

    def test_rpc_provider_whitelisted(self):
        from wiki.entity_filter import HubNodeDetector

        modules = [
            ModuleInfo(name="RpcProv", path="rpc.py", uid="uid_rpc", semantic_roles=["rpc_provider"]),
        ] + [ModuleInfo(name=f"m{i}", path=f"m{i}.py", uid=f"uid_{i}") for i in range(9)]
        edges = [ModuleEdge(source="RpcProv", target=f"m{i}", edge_type="CALLS") for i in range(9)]
        edges += [ModuleEdge(source=f"m{i}", target="RpcProv", edge_type="CALLS") for i in range(9)]
        graph = ModuleGraph(modules=modules, edges=edges, entry_points=["RpcProv"])
        detector = HubNodeDetector()
        hubs = detector.detect_hubs(graph, percentile=90)
        assert "RpcProv" not in hubs
