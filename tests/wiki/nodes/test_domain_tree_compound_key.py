"""Tests for compound-key module serialization in domain_tree (Batch T)."""

from store.schema import GraphNode, NodeLabel
from wiki.nodes.graph_domain_decompose import _build_domain_tree, _sub_to_tree_node
from wiki.pipeline_orchestrator import domain_tree_to_mapping


def test_build_domain_tree_uses_compound_keys():
    """Two repos with same module name produce distinct compound keys in tree."""
    communities_named = [
        {
            "slug": "user-domain",
            "display_name": "User Domain",
            "modules": [("repo_a", "UserService"), ("repo_b", "UserService")],
        }
    ]
    tree = _build_domain_tree(communities_named, {})
    assert tree[0]["modules"] == ["repo_a|UserService", "repo_b|UserService"]


def test_sub_to_tree_node_uses_compound_keys():
    """Leaf sub-domain nodes store compound keys, not bare names."""
    sub = {
        "slug": "auth",
        "display_name": "Auth",
        "modules": [("repo_a", "AuthService"), ("repo_b", "AuthService")],
        "children": [],
    }
    node = _sub_to_tree_node(sub)
    assert node["modules"] == ["repo_a|AuthService", "repo_b|AuthService"]
    assert node["children"] == []


def test_build_domain_tree_nested_subdomains_compound_keys():
    """Sub-tree leaf nodes also use compound keys."""
    communities_named = [
        {
            "slug": "platform",
            "display_name": "Platform",
            "modules": [("repo_a", "Core"), ("repo_b", "Core")],
        }
    ]
    sub_trees = {
        "platform": [
            {
                "slug": "auth",
                "display_name": "Auth",
                "modules": [("repo_a", "AuthService")],
                "children": [],
            },
            {
                "slug": "user",
                "display_name": "User",
                "modules": [("repo_b", "UserService")],
                "children": [],
            },
        ]
    }
    tree = _build_domain_tree(communities_named, sub_trees)
    assert tree[0]["modules"] == []
    children = tree[0]["children"]
    assert len(children) == 2
    assert children[0]["modules"] == ["repo_a|AuthService"]
    assert children[1]["modules"] == ["repo_b|UserService"]


def test_domain_tree_to_mapping_parses_compound_keys():
    """Mapping disambiguates same-name modules from different repos."""
    tree = [
        {
            "name": "user-domain",
            "display_name": "User Domain",
            "modules": ["repo_a|UserService", "repo_b|UserService"],
            "children": [],
        }
    ]
    all_modules = {
        "repo_a": [GraphNode(label=NodeLabel.MODULE, properties={"name": "UserService"})],
        "repo_b": [GraphNode(label=NodeLabel.MODULE, properties={"name": "UserService"})],
    }
    mapping = domain_tree_to_mapping(tree, all_modules)
    pairs = mapping["user-domain"]
    assert ("repo_a", "UserService") in pairs
    assert ("repo_b", "UserService") in pairs
    assert len(pairs) == 2


def test_domain_tree_to_mapping_bare_name_fallback():
    """Legacy trees with bare module names still map via first-repo-wins."""
    tree = [
        {
            "name": "legacy-domain",
            "display_name": "Legacy",
            "modules": ["UserService"],
            "children": [],
        }
    ]
    all_modules = {
        "repo_a": [GraphNode(label=NodeLabel.MODULE, properties={"name": "UserService"})],
        "repo_b": [GraphNode(label=NodeLabel.MODULE, properties={"name": "UserService"})],
    }
    mapping = domain_tree_to_mapping(tree, all_modules)
    assert mapping["legacy-domain"] == [("repo_a", "UserService")]
