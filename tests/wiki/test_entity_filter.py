"""Tests for wiki.entity_filter — EntityStrategy classification."""

from __future__ import annotations

from store.schema import GraphNode, NodeLabel
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
