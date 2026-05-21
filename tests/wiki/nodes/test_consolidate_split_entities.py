"""Tests for _consolidate_split_entities post-classification merge."""

from wiki.nodes.classify import _consolidate_split_entities


def test_family_modules_consolidated_to_majority_domain():
    mapping = {
        "infrastructure": [("r", "FamilyWebService"), ("r", "FamilyChest")],
        "family-system": [
            ("r", "FamilyMoa"),
            ("r", "FamilyTask"),
            ("r", "FamilyPower"),
        ],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    family_mods = {m for _, m in result.get("family-system", [])}
    assert "FamilyWebService" in family_mods
    assert "FamilyChest" in family_mods
    assert "FamilyMoa" in family_mods


def test_generic_prefix_not_consolidated():
    mapping = {
        "user-info": [("r", "UserProfile"), ("r", "UserExtend"), ("r", "UserAvatar")],
        "membership": [("r", "UserVip"), ("r", "UserLevel"), ("r", "UserPay")],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    assert len(result.get("user-info", [])) == 3
    assert len(result.get("membership", [])) == 3


def test_no_move_when_single_domain():
    mapping = {
        "family": [("r", "FamilyA"), ("r", "FamilyB"), ("r", "FamilyC")],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    assert len(result["family"]) == 3


def test_prefix_below_threshold_not_consolidated():
    mapping = {
        "dom-a": [("r", "FooService")],
        "dom-b": [("r", "FooHandler")],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    assert len(result["dom-a"]) == 1
    assert len(result["dom-b"]) == 1


def test_empty_mapping_returns_empty():
    result, names = _consolidate_split_entities({}, {})
    assert result == {}
    assert names == {}


def test_display_names_preserved():
    mapping = {
        "infra": [("r", "IntimacyWeb")],
        "intimacy": [("r", "IntimacyService"), ("r", "IntimacyTask"), ("r", "IntimacyDao")],
    }
    display = {"infra": "基础设施", "intimacy": "亲密关系"}
    _, result_display = _consolidate_split_entities(mapping, display)
    assert result_display == display
