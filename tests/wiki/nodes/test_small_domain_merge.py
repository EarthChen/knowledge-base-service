"""Tests for small leaf domain merge during graph domain decomposition."""

from __future__ import annotations

from wiki.nodes.graph_domain_decompose import _merge_small_leaf_domains


def _tree_node(
    name: str,
    modules: list[tuple[str, str]] | None = None,
    *,
    display_name: str = "",
    children: list[dict] | None = None,
) -> dict:
    mod_keys = [f"{repo}|{mod}" for repo, mod in (modules or [])]
    return {
        "name": name,
        "display_name": display_name or name,
        "modules": mod_keys,
        "children": children or [],
    }


def test_small_domain_merged_to_sibling():
    domain_mapping = {
        "big-sibling": [("repo", "A"), ("repo", "B"), ("repo", "C")],
        "small-leaf": [("repo", "X")],
        "mid-sibling": [("repo", "Y"), ("repo", "Z"), ("repo", "W")],
    }
    domain_display_names = {
        "big-sibling": "Big",
        "small-leaf": "Small",
        "mid-sibling": "Mid",
    }
    domain_tree = [
        _tree_node(
            "parent-shell",
            display_name="Parent",
            children=[
                _tree_node("big-sibling", [("repo", "A"), ("repo", "B"), ("repo", "C")]),
                _tree_node("small-leaf", [("repo", "X")]),
                _tree_node("mid-sibling", [("repo", "Y"), ("repo", "Z"), ("repo", "W")]),
            ],
        ),
    ]

    merged_mapping, merged_names = _merge_small_leaf_domains(
        domain_mapping, domain_display_names, domain_tree, min_modules=3, budget_max=20,
    )

    assert "small-leaf" not in merged_mapping
    assert len(merged_mapping["big-sibling"]) == 4
    assert ("repo", "X") in merged_mapping["big-sibling"]
    assert merged_names["big-sibling"] == "Big"


def test_small_domain_merged_to_parent():
    domain_mapping = {
        "parent-shell": [("repo", "P")],
        "only-child": [("repo", "A")],
    }
    domain_display_names = {
        "parent-shell": "Parent",
        "only-child": "Only Child",
    }
    domain_tree = [
        _tree_node(
            "parent-shell",
            [("repo", "P")],
            display_name="Parent",
            children=[
                _tree_node("only-child", [("repo", "A")]),
            ],
        ),
    ]

    merged_mapping, merged_names = _merge_small_leaf_domains(
        domain_mapping, domain_display_names, domain_tree, min_modules=3, budget_max=20,
    )

    assert "only-child" not in merged_mapping
    assert len(merged_mapping["parent-shell"]) == 2
    assert ("repo", "A") in merged_mapping["parent-shell"]
    assert merged_names["parent-shell"] == "Parent"


def test_domain_above_threshold_not_merged():
    domain_mapping = {
        "healthy-leaf": [("repo", "A"), ("repo", "B"), ("repo", "C")],
        "small-leaf": [("repo", "X")],
    }
    domain_display_names = {
        "healthy-leaf": "Healthy",
        "small-leaf": "Small",
    }
    domain_tree = [
        _tree_node(
            "group",
            children=[
                _tree_node("healthy-leaf", [("repo", "A"), ("repo", "B"), ("repo", "C")]),
                _tree_node("small-leaf", [("repo", "X")]),
            ],
        ),
    ]

    merged_mapping, _ = _merge_small_leaf_domains(
        domain_mapping, domain_display_names, domain_tree, min_modules=3, budget_max=20,
    )

    assert "healthy-leaf" in merged_mapping
    assert len(merged_mapping["healthy-leaf"]) == 4
    assert ("repo", "X") in merged_mapping["healthy-leaf"]


def test_no_parent_small_domain_preserved():
    domain_mapping = {
        "lonely-small": [("repo", "A")],
    }
    domain_display_names = {"lonely-small": "Lonely"}
    domain_tree = [_tree_node("lonely-small", [("repo", "A")])]

    merged_mapping, merged_names = _merge_small_leaf_domains(
        domain_mapping, domain_display_names, domain_tree, min_modules=3, budget_max=20,
    )

    assert "lonely-small" in merged_mapping
    assert len(merged_mapping["lonely-small"]) == 1
    assert merged_names["lonely-small"] == "Lonely"


def test_config_defaults_updated():
    from core.config import AppWikiFlags

    cfg = AppWikiFlags()
    assert cfg.domain_budget_max == 20
    assert cfg.skip_llm_merge_when_corrector_enabled is False
    assert cfg.min_modules_per_leaf_domain == 3


def test_multiple_small_domains_consolidated():
    domain_mapping = {
        "target": [("repo", "A"), ("repo", "B"), ("repo", "C")],
        "tiny-a": [("repo", "X")],
        "tiny-b": [("repo", "Y")],
        "tiny-c": [("repo", "Z")],
    }
    domain_display_names = {
        "target": "Target",
        "tiny-a": "Tiny A",
        "tiny-b": "Tiny B",
        "tiny-c": "Tiny C",
    }
    domain_tree = [
        _tree_node(
            "group",
            children=[
                _tree_node("target", [("repo", "A"), ("repo", "B"), ("repo", "C")]),
                _tree_node("tiny-a", [("repo", "X")]),
                _tree_node("tiny-b", [("repo", "Y")]),
                _tree_node("tiny-c", [("repo", "Z")]),
            ],
        ),
    ]

    merged_mapping, _ = _merge_small_leaf_domains(
        domain_mapping, domain_display_names, domain_tree, min_modules=3, budget_max=20,
    )

    assert "tiny-a" not in merged_mapping
    assert "tiny-b" not in merged_mapping
    assert "tiny-c" not in merged_mapping
    assert len(merged_mapping["target"]) == 6
