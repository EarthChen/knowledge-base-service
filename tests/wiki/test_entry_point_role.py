"""Tests for WikiEntityRole.ENTRY_POINT classification."""
from __future__ import annotations

from store.schema import GraphNode, NodeLabel
from wiki.entity_role_classifier import (
    DOMAIN_CLASSIFICATION_ENTITY_ROLES,
    EntityRoleClassifier,
    WikiEntityRole,
)


def _node(
    name: str,
    label: NodeLabel = NodeLabel.MODULE,
    *,
    annotations: list[str] | None = None,
    methods: list[str] | None = None,
    methods_count: int = 0,
    start_line: int = 0,
    end_line: int = 50,
    semantic_roles: list[str] | None = None,
    is_enum: bool = False,
) -> GraphNode:
    props: dict = {
        "name": name,
        "methods_count": methods_count,
        "start_line": start_line,
        "end_line": end_line,
        "is_enum": is_enum,
    }
    if annotations:
        props["annotations"] = annotations
    if methods is not None:
        props["methods"] = methods
    if semantic_roles:
        props["semantic_roles"] = semantic_roles
    return GraphNode(label=label, properties=props, uid=f"Module::{name}:0")


def test_entry_point_main_method():
    node = _node("CliApp", methods=["run", "main"], methods_count=2)
    c = EntityRoleClassifier()
    assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.ENTRY_POINT


def test_entry_point_http_handler_annotation():
    node = _node(
        "Api",
        annotations=["@RestController", "@RequestMapping(\"/api\")"],
        methods_count=1,
        start_line=0,
        end_line=40,
    )
    c = EntityRoleClassifier()
    assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.ENTRY_POINT


def test_entry_point_flask_route():
    node = _node(
        "views",
        annotations=["@app.route(\"/health\")"],
        methods_count=1,
        start_line=0,
        end_line=30,
    )
    c = EntityRoleClassifier()
    assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.ENTRY_POINT


def test_entry_point_filename_controller():
    node = _node(
        "OrderController",
        methods_count=2,
        start_line=0,
        end_line=25,
    )
    c = EntityRoleClassifier()
    assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.ENTRY_POINT


def test_entry_point_backward_compat_in_domain_filter():
    assert WikiEntityRole.HAS_BUSINESS_LOGIC in DOMAIN_CLASSIFICATION_ENTITY_ROLES
    assert WikiEntityRole.ENTRY_POINT in DOMAIN_CLASSIFICATION_ENTITY_ROLES
    assert DOMAIN_CLASSIFICATION_ENTITY_ROLES == frozenset({
        WikiEntityRole.HAS_BUSINESS_LOGIC,
        WikiEntityRole.ENTRY_POINT,
        WikiEntityRole.SUPPORTING,
    })


def test_non_entry_point_normal_service():
    node = _node(
        "OrderService",
        annotations=["@Service"],
        methods_count=10,
        start_line=0,
        end_line=300,
    )
    c = EntityRoleClassifier()
    role = c.classify(node, edge_count=20, children_count=3)
    assert role != WikiEntityRole.ENTRY_POINT
    assert role == WikiEntityRole.HAS_BUSINESS_LOGIC
