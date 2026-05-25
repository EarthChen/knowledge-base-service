"""Tests for Batch AG architecture P2/P3 fixes."""
from __future__ import annotations

import typing
import warnings

import pytest

from wiki.nodes.classify import _reconcile_tree_with_mapping


def test_reconcile_tree_preserves_cross_repo_same_name_modules() -> None:
    """Two repos with same module name must both survive reconciliation."""
    tree = [
        {
            "name": "user-domain",
            "display_name": "User Domain",
            "modules": ["repo_a|UserService", "repo_b|UserService"],
            "children": [],
        }
    ]
    mapping = {
        "user-domain": [
            ("repo_a", "UserService"),
            ("repo_b", "UserService"),
        ],
    }

    _reconcile_tree_with_mapping(tree, mapping)

    modules = tree[0]["modules"]
    assert "repo_a|UserService" in modules
    assert "repo_b|UserService" in modules
    assert len(modules) == 2


def test_reconcile_tree_moves_misplaced_compound_module() -> None:
    """Compound-key module in wrong domain is moved to mapping target."""
    tree = [
        {
            "name": "wrong-domain",
            "display_name": "Wrong",
            "modules": ["repo_b|UserService"],
            "children": [],
        },
        {
            "name": "user-domain",
            "display_name": "User Domain",
            "modules": [],
            "children": [],
        },
    ]
    mapping = {
        "user-domain": [("repo_b", "UserService")],
    }

    _reconcile_tree_with_mapping(tree, mapping)

    assert tree[0]["modules"] == []
    assert tree[1]["modules"] == ["repo_b|UserService"]


def test_reconcile_tree_bare_name_legacy_fallback() -> None:
    """Legacy trees with bare module names still reconcile when unambiguous."""
    tree = [
        {
            "name": "legacy-domain",
            "display_name": "Legacy",
            "modules": ["UserService"],
            "children": [],
        }
    ]
    mapping = {
        "legacy-domain": [("repo_a", "UserService")],
    }

    _reconcile_tree_with_mapping(tree, mapping)

    assert "UserService" in tree[0]["modules"]


def test_pipeline_state_existing_domain_mapping_type() -> None:
    """existing_domain_mapping is slug -> list of (repo, module) pairs."""
    from wiki.pipeline_state import WikiPipelineState

    hints = typing.get_type_hints(WikiPipelineState)
    assert hints["existing_domain_mapping"] == dict[str, list[tuple[str, str]]]

    state: WikiPipelineState = {
        "business_id": "test-biz",
        "repositories": ["repo-a"],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "errors": [],
        "entity_roles": {},
        "role_stats": {},
        "is_incremental": False,
        "reorg_type": "",
        "affected_domains": [],
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
        "existing_domain_mapping": {
            "user-domain": [("repo_a", "UserService"), ("repo_b", "UserService")],
        },
    }
    pairs = state["existing_domain_mapping"]["user-domain"]
    assert pairs == [("repo_a", "UserService"), ("repo_b", "UserService")]


def test_deprecated_compose_nodes_not_in_nodes_all() -> None:
    import wiki.nodes as nodes_pkg

    assert "compose_leaf_pages_node" not in nodes_pkg.__all__
    assert "plan_topic_structure_node" not in nodes_pkg.__all__


@pytest.mark.asyncio
async def test_deprecated_compose_nodes_still_importable_with_warning() -> None:
    from wiki.nodes.compose import compose_leaf_pages_node, plan_topic_structure_node

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await compose_leaf_pages_node({}, {"configurable": {}})
        await plan_topic_structure_node({}, {"configurable": {}})

    messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any("compose_domain_agents_node" in m for m in messages)
    assert len([m for m in messages if "compose_domain_agents_node" in m]) >= 2
