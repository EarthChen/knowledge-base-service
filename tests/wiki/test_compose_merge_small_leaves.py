"""Test small leaf domain merging at compose stage."""
import pytest


def test_small_leaves_merged_into_sibling():
    """Leaves with < 3 modules should be merged into same-parent large leaf."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "Auth", "modules": ["AuthService", "AuthDAO", "AuthController"], "parent": "root"},
        {"name": "Login", "modules": ["LoginService"], "parent": "root"},
        {"name": "Payment", "modules": ["PayService", "PayDAO", "PayGateway"], "parent": "root"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 2
    login_modules_found = False
    for leaf in result:
        if "LoginService" in leaf["modules"]:
            login_modules_found = True
            assert leaf["parent"] == "root"
    assert login_modules_found


def test_all_small_leaves_first_promoted():
    """When all leaves are small, the first one should be promoted to large."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "A", "modules": ["M1"], "parent": "root"},
        {"name": "B", "modules": ["M2", "M3"], "parent": "root"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 1
    assert set(result[0]["modules"]) == {"M1", "M2", "M3"}


def test_no_merge_when_all_large():
    """When all leaves have >= min_modules, no merging should happen."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "A", "modules": ["M1", "M2", "M3"], "parent": "root"},
        {"name": "B", "modules": ["M4", "M5", "M6"], "parent": "root"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 2


def test_prefer_same_parent_for_merge():
    """Small leaves should prefer merging into same-parent large leaf."""
    from wiki.nodes.compose import _merge_small_leaves

    leaves = [
        {"name": "BigA", "modules": ["M1", "M2", "M3"], "parent": "DomainX"},
        {"name": "SmallA", "modules": ["M4"], "parent": "DomainX"},
        {"name": "BigB", "modules": ["M5", "M6", "M7"], "parent": "DomainY"},
    ]

    result = _merge_small_leaves(leaves, min_modules=3)

    assert len(result) == 2
    for leaf in result:
        if leaf["name"] == "BigA":
            assert "M4" in leaf["modules"]
