"""Tests for prefix-family grouping."""
from __future__ import annotations


def test_groups_same_prefix_l1_domains():
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m1"], "children": []},
        {"name": "intimacy-online", "display_name": "亲密度在线", "modules": ["m2"], "children": []},
        {"name": "family-core", "display_name": "家族核心", "modules": ["m3"], "children": []},
    ]
    result = enforce_prefix_family_grouping(tree)
    # Two intimacy domains should be grouped
    intimacy_parents = [n for n in result if "intimacy" in n.get("name", "") and n.get("children")]
    assert len(intimacy_parents) >= 1
    assert len(intimacy_parents[0]["children"]) >= 2


def test_reparents_under_existing_parent():
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "relations", "display_name": "关系", "modules": [], "children": [
            {"name": "intimacy-core", "display_name": "亲密度核心", "modules": ["m1"], "children": []},
        ]},
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m2"], "children": []},
    ]
    result = enforce_prefix_family_grouping(tree)
    # intimacy-task-execution reparented under relations shell (has intimacy child)
    assert len(result) == 1
    relations = result[0]
    assert relations["name"] == "relations"
    child_names = [c["name"] for c in relations["children"]]
    assert "intimacy-core" in child_names
    assert "intimacy-task-execution" in child_names


def test_skips_user_modified():
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "intimacy-a", "display_name": "A", "modules": ["m1"], "children": [], "user_modified": True},
        {"name": "intimacy-b", "display_name": "B", "modules": ["m2"], "children": []},
        {"name": "intimacy-c", "display_name": "C", "modules": ["m3"], "children": []},
    ]
    result = enforce_prefix_family_grouping(tree)
    # intimacy-a is protected; b+c can group (2 nodes)
    grouped = [n for n in result if n.get("children") and "intimacy" in n.get("name", "")]
    # b and c grouped, a stays separate
    l1_names = [n["name"] for n in result]
    assert "intimacy-a" in l1_names


def test_small_tree_unchanged():
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "domain-a", "display_name": "A", "modules": ["m1"], "children": []},
    ]
    result = enforce_prefix_family_grouping(tree)
    assert result == tree


def test_two_same_prefix_l1_get_wrapped():
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "family-core", "display_name": "家族核心", "modules": ["m1"], "children": []},
        {"name": "family-chest", "display_name": "家族宝箱", "modules": ["m2"], "children": []},
    ]
    result = enforce_prefix_family_grouping(tree)
    # Should be wrapped under family-family parent
    assert len(result) == 1
    assert len(result[0].get("children", [])) == 2


def test_cross_level_reparent_intimacy_under_relation():
    """intimacy-task-execution at L1 should move under shell that has intimacy children."""
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "relation", "display_name": "关系", "modules": [], "children": [
            {"name": "intimacy-relationship", "display_name": "亲密度关系", "modules": ["m1"], "children": []},
            {"name": "closed-friendship-lifecycle", "display_name": "挚友关系", "modules": ["m2"], "children": []},
        ]},
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m3"], "children": []},
        {"name": "family", "display_name": "家族", "modules": [], "children": [
            {"name": "family-core-operations", "display_name": "家族核心", "modules": ["m4"], "children": []},
        ]},
    ]
    result = enforce_prefix_family_grouping(tree)
    relation = next(n for n in result if n["name"] == "relation")
    child_names = [c["name"] for c in relation["children"]]
    assert "intimacy-task-execution" in child_names
    l1_names = [n["name"] for n in result]
    assert "intimacy-task-execution" not in l1_names


def test_cross_level_skips_user_modified():
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "relation", "display_name": "关系", "modules": [], "children": [
            {"name": "intimacy-relationship", "display_name": "亲密度关系", "modules": ["m1"], "children": []},
        ]},
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m3"], "children": [], "user_modified": True},
    ]
    result = enforce_prefix_family_grouping(tree)
    l1_names = [n["name"] for n in result]
    assert "intimacy-task-execution" in l1_names


def test_cross_level_no_move_when_no_matching_shell():
    from wiki.prefix_family_grouper import enforce_prefix_family_grouping

    tree = [
        {"name": "relation", "display_name": "关系", "modules": [], "children": [
            {"name": "closed-friendship-lifecycle", "display_name": "挚友", "modules": ["m1"], "children": []},
        ]},
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m3"], "children": []},
    ]
    result = enforce_prefix_family_grouping(tree)
    l1_names = [n["name"] for n in result]
    assert "intimacy-task-execution" in l1_names
