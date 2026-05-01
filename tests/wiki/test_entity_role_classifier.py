from __future__ import annotations

import pytest
from store.schema import GraphNode, NodeLabel
from wiki.entity_role_classifier import EntityRoleClassifier, WikiEntityRole


def _node(
    name: str,
    label: NodeLabel = NodeLabel.MODULE,
    *,
    annotations: list[str] | None = None,
    methods_count: int = 0,
    start_line: int = 0,
    end_line: int = 50,
    semantic_roles: list[str] | None = None,
    is_interface: bool = False,
    is_enum: bool = False,
) -> GraphNode:
    props: dict = {
        "name": name,
        "methods_count": methods_count,
        "start_line": start_line,
        "end_line": end_line,
        "is_interface": is_interface,
        "is_enum": is_enum,
    }
    if annotations:
        props["annotations"] = annotations
    if semantic_roles:
        props["semantic_roles"] = semantic_roles
    return GraphNode(label=label, properties=props, uid=f"Module::{name}:0")


class TestPhase1DeterministicRules:
    """Phase 1: deterministic fast-path rules."""

    def test_data_annotation_is_data_model(self):
        node = _node("UserDTO", annotations=["@Data"], methods_count=1)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.DATA_MODEL

    def test_dto_suffix_is_data_model(self):
        node = _node("PaymentRequestDTO", methods_count=5)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=3, children_count=2) == WikiEntityRole.DATA_MODEL

    def test_enum_is_data_model(self):
        node = _node("StatusEnum", is_enum=True, methods_count=0)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.DATA_MODEL

    def test_empty_shell_is_noise(self):
        node = _node("EmptyConfig", methods_count=0, start_line=0, end_line=5)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.FRAMEWORK_NOISE

    def test_pure_config_class_is_noise(self):
        node = _node("AppConfig", annotations=["@Configuration"], methods_count=0)
        c = EntityRoleClassifier()
        assert c.classify(node, edge_count=0, children_count=0) == WikiEntityRole.FRAMEWORK_NOISE


class TestPhase2ScoringModel:
    """Phase 2: business logic density scoring for entities not caught by Phase 1."""

    def test_controller_with_methods_is_entry_point(self):
        node = _node(
            "PaymentController",
            annotations=["@RestController"],
            methods_count=8,
            semantic_roles=["http_controller"],
            start_line=0,
            end_line=200,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=15, children_count=5)
        assert result == WikiEntityRole.ENTRY_POINT

    def test_service_with_calls_is_business_logic(self):
        node = _node(
            "OrderService",
            annotations=["@Service"],
            methods_count=10,
            start_line=0,
            end_line=300,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=20, children_count=3)
        assert result == WikiEntityRole.HAS_BUSINESS_LOGIC

    def test_low_score_entity_is_supporting(self):
        node = _node(
            "HelperUtil",
            methods_count=3,
            start_line=0,
            end_line=40,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=2, children_count=0)
        assert result == WikiEntityRole.SUPPORTING

    def test_minimal_methods_no_role_is_data_model(self):
        node = _node(
            "SimpleWrapper",
            methods_count=1,
            start_line=0,
            end_line=15,
        )
        c = EntityRoleClassifier()
        result = c.classify(node, edge_count=0, children_count=0)
        assert result == WikiEntityRole.DATA_MODEL


class TestScoreComputation:
    """Verify the raw score computation."""

    def test_score_method(self):
        node = _node(
            "SomeService",
            annotations=["@Service"],
            methods_count=6,
            start_line=0,
            end_line=150,
        )
        c = EntityRoleClassifier()
        score = c.compute_score(node, edge_count=10, children_count=2)
        assert 0 <= score <= 100
        assert score >= 40  # should qualify as HAS_BUSINESS_LOGIC
