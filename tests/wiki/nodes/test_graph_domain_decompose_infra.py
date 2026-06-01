"""Tests for infrastructure module detection and filtering fixes (SB1 + SB2)."""
from __future__ import annotations

import pytest


class TestInfraClassSuffixPrecision:
    """SB2: Handler suffix should not catch business handlers."""

    def test_family_task_handler_not_infra(self):
        from wiki.nodes.graph_domain_decompose import _detect_infra_modules

        modules = [("repo", "FamilyTaskHandler"), ("repo", "FamilyService")]
        result = _detect_infra_modules(modules, {}, [], path_patterns=[])
        assert ("repo", "FamilyTaskHandler") not in result

    def test_intimacy_level_handler_not_infra(self):
        from wiki.nodes.graph_domain_decompose import _detect_infra_modules

        modules = [("repo", "IntimacyLevelHandler")]
        result = _detect_infra_modules(modules, {}, [], path_patterns=[])
        assert ("repo", "IntimacyLevelHandler") not in result

    def test_closed_friend_relation_change_handler_not_infra(self):
        from wiki.nodes.graph_domain_decompose import _detect_infra_modules

        modules = [("repo", "ClosedFriendRelationChangeHandler")]
        result = _detect_infra_modules(modules, {}, [], path_patterns=[])
        assert ("repo", "ClosedFriendRelationChangeHandler") not in result

    def test_generic_message_handler_is_infra(self):
        from wiki.nodes.graph_domain_decompose import _detect_infra_modules

        modules = [("repo", "MessageHandler"), ("repo", "SomeService")]
        result = _detect_infra_modules(modules, {}, [], path_patterns=[])
        assert ("repo", "MessageHandler") in result

    def test_type_handler_still_infra(self):
        from wiki.nodes.graph_domain_decompose import _detect_infra_modules

        modules = [("repo", "LongTimestampTypeHandler")]
        result = _detect_infra_modules(modules, {}, [], path_patterns=[])
        assert ("repo", "LongTimestampTypeHandler") in result


class TestFilterInfraSubDomains:
    """SB1: Infra sub-domain modules should NOT merge into business siblings."""

    def test_infra_sub_domain_not_merged_into_sibling(self):
        from wiki.nodes.graph_domain_decompose import _filter_infra_sub_domains

        named_subs = [
            {"slug": "family-core", "modules": [("r", "FamilyService")], "children": []},
            {"slug": "config-infra", "modules": [("r", "AppConfig")], "children": []},
        ]
        result = _filter_infra_sub_domains(named_subs, ["config", "infra"])
        # config-infra should be removed, NOT merged into family-core
        assert len(result) == 1
        assert result[0]["slug"] == "family-core"
        assert len(result[0]["modules"]) == 1  # NOT 2!

    def test_no_infra_returns_unchanged(self):
        from wiki.nodes.graph_domain_decompose import _filter_infra_sub_domains

        named_subs = [
            {"slug": "family-core", "modules": [("r", "FamilyService")], "children": []},
            {"slug": "family-chest", "modules": [("r", "ChestService")], "children": []},
        ]
        result = _filter_infra_sub_domains(named_subs, ["config", "infra"])
        assert len(result) == 2
