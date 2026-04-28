"""Tests for _entity_digest enhancements (annotations, structured output, etc.)."""

from dataclasses import dataclass, field

from store.schema import GraphEdge, GraphNode, NodeLabel, EdgeType
from wiki.composer import (
    WikiComposer,
    _STRUCTURED_SECTIONS_MODULE,
    _STRUCTURED_SECTIONS_CLASS,
    _STRUCTURED_SECTIONS_FUNCTION,
)
from wiki.data_collector import PageData
from wiki.models import CodeSnippet, PageType, SourceLocation


def _make_node(label: NodeLabel = NodeLabel.CLASS, **overrides):
    props = {
        "name": "AuthService",
        "path": "src/auth.py",
        "fqn": "src.auth.AuthService",
        "signature": "class AuthService",
        "docstring": "Handles authentication",
        "annotations": ["@Service", "@Transactional"],
        "semantic_roles": ["service", "authentication"],
        "base_classes": ["BaseService"],
        "interfaces": ["Authenticator"],
    }
    props.update(overrides)
    return GraphNode(label=label, properties=props)


def _make_page_data(node, *, edges=None, children=None, methods=None):
    return PageData(
        node=node,
        edges=edges or [],
        children=children or [],
        source_location=SourceLocation("src/auth.py", 1, 100, "src.auth.AuthService", "test-repo"),
        method_locations=[],
        business_summary=None,
        methods=methods or [],
    )


def _composer_instance():
    c = WikiComposer.__new__(WikiComposer)
    return c


class TestEntityDigestAnnotations:
    def test_includes_annotations(self):
        c = _composer_instance()
        node = _make_node()
        digest = c._entity_digest(_make_page_data(node), PageType.CLASS_DETAIL)
        assert "Annotations: @Service, @Transactional" in digest

    def test_includes_semantic_roles(self):
        c = _composer_instance()
        node = _make_node()
        digest = c._entity_digest(_make_page_data(node), PageType.CLASS_DETAIL)
        assert "Semantic roles: service, authentication" in digest

    def test_includes_base_classes(self):
        c = _composer_instance()
        node = _make_node()
        digest = c._entity_digest(_make_page_data(node), PageType.CLASS_DETAIL)
        assert "Base classes: BaseService" in digest

    def test_includes_interfaces(self):
        c = _composer_instance()
        node = _make_node()
        digest = c._entity_digest(_make_page_data(node), PageType.CLASS_DETAIL)
        assert "Implements: Authenticator" in digest

    def test_skips_empty_annotations(self):
        c = _composer_instance()
        node = _make_node(annotations=[], semantic_roles=[], base_classes=[], interfaces=[])
        digest = c._entity_digest(_make_page_data(node), PageType.CLASS_DETAIL)
        assert "Annotations:" not in digest
        assert "Semantic roles:" not in digest


class TestEntityDigestMethodParams:
    def test_method_params_and_return_type(self):
        c = _composer_instance()
        node = _make_node()
        method = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={
                "name": "authenticate",
                "signature": "def authenticate(user, password)",
                "parameters": ["user:str", "password:str"],
                "return_type": "bool",
            },
        )
        digest = c._entity_digest(
            _make_page_data(node, methods=[method]),
            PageType.CLASS_DETAIL,
        )
        assert "params:" in digest
        assert "returns:" in digest


class TestEntityDigestModuleOverview:
    def test_module_children_with_annotations(self):
        c = _composer_instance()
        node = _make_node(label=NodeLabel.MODULE, name="auth", path="auth/")
        child = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "LoginHandler",
                "annotations": ["@Controller"],
                "business_summary": "Handles login flow",
            },
        )
        digest = c._entity_digest(
            _make_page_data(node, children=[child]),
            PageType.MODULE_OVERVIEW,
        )
        assert "LoginHandler" in digest
        assert "@Controller" in digest

    def test_module_docstring_in_generic_section(self):
        c = _composer_instance()
        node = _make_node(
            label=NodeLabel.MODULE,
            name="auth",
            path="auth/",
            docstring="Authentication module for user management",
        )
        digest = c._entity_digest(_make_page_data(node), PageType.MODULE_OVERVIEW)
        assert "Docstring: Authentication module" in digest


class TestStructuredSectionConstants:
    def test_module_sections(self):
        assert "Purpose & Responsibility" in _STRUCTURED_SECTIONS_MODULE
        assert "Key Components" in _STRUCTURED_SECTIONS_MODULE

    def test_class_sections(self):
        assert "Purpose & Responsibility" in _STRUCTURED_SECTIONS_CLASS
        assert "Methods & Properties" in _STRUCTURED_SECTIONS_CLASS

    def test_function_sections(self):
        assert "Purpose" in _STRUCTURED_SECTIONS_FUNCTION
        assert "Parameters & Return" in _STRUCTURED_SECTIONS_FUNCTION
