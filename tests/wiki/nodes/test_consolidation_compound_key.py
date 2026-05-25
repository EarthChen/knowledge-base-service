"""Tests for compound-key prefix consolidation (cross-repo collision fix)."""

from wiki.nodes.classify import _consolidate_split_entities


def test_cross_repo_same_prefix_not_consolidated():
    """Modules with the same prefix in different repos must not merge domains."""
    mapping = {
        "user-info": [
            ("repo-a", "FamilyService"),
            ("repo-a", "FamilyDao"),
        ],
        "membership": [
            ("repo-b", "FamilyHelper"),
            ("repo-b", "FamilyMapper"),
            ("repo-b", "FamilyTask"),
        ],
    }
    result, _ = _consolidate_split_entities(mapping, {})

    repo_a_mods = {(r, m) for r, m in result.get("user-info", [])}
    assert ("repo-a", "FamilyService") in repo_a_mods
    assert ("repo-a", "FamilyDao") in repo_a_mods

    repo_b_mods = {(r, m) for r, m in result.get("membership", [])}
    assert ("repo-b", "FamilyHelper") in repo_b_mods
    assert ("repo-b", "FamilyMapper") in repo_b_mods
    assert ("repo-b", "FamilyTask") in repo_b_mods


def test_same_repo_prefix_modules_consolidated():
    """Same-repo prefix modules split across domains should consolidate."""
    mapping = {
        "infrastructure": [("repo-a", "FamilyWebService"), ("repo-a", "FamilyChest")],
        "family-system": [
            ("repo-a", "FamilyMoa"),
            ("repo-a", "FamilyTask"),
            ("repo-a", "FamilyPower"),
        ],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    family_mods = {m for _, m in result.get("family-system", [])}
    assert "FamilyWebService" in family_mods
    assert "FamilyChest" in family_mods
    assert "FamilyMoa" in family_mods


def test_single_repo_no_prefix_match_no_moves():
    """Below-threshold prefix groups in one repo should not move modules."""
    mapping = {
        "dom-a": [("repo-a", "FooService")],
        "dom-b": [("repo-a", "FooHandler")],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    assert len(result["dom-a"]) == 1
    assert len(result["dom-b"]) == 1
