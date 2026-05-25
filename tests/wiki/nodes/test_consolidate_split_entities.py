"""Tests for _consolidate_split_entities post-classification merge."""

from unittest.mock import MagicMock

import pytest

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


def test_db_io_prefixes_consolidated():
    """Db and Io are meaningful business prefixes, not generic."""
    mapping = {
        "storage": [("r", "DbUtil"), ("r", "DbPool"), ("r", "DbConfig")],
        "network": [("r", "DbMigration")],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    db_mods = {m for _, m in result.get("storage", [])}
    assert "DbMigration" in db_mods
    assert len(db_mods) == 4


def test_snake_case_prefix_consolidated():
    mapping = {
        "user-core": [("r", "user_service"), ("r", "user_dao"), ("r", "user_handler")],
        "billing": [("r", "user_billing")],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    user_mods = {m for _, m in result.get("user-core", [])}
    assert "user_billing" in user_mods


def test_configurable_thresholds(monkeypatch):
    """Lower consolidation_min_count allows 2-module prefix groups."""
    mock_wiki = MagicMock()
    mock_wiki.consolidation_min_count = 2
    mock_wiki.consolidation_min_domains = 2
    mock_settings = MagicMock()
    mock_settings.wiki = mock_wiki
    monkeypatch.setattr("wiki.nodes.classify.get_settings", lambda: mock_settings)

    mapping = {
        "dom-a": [("r", "PayService"), ("r", "PayDao")],
        "dom-b": [("r", "PayHandler")],
    }
    result, _ = _consolidate_split_entities(mapping, {})
    pay_mods = {m for _, m in result.get("dom-a", [])}
    assert len(pay_mods) == 3
    assert "PayHandler" in pay_mods
