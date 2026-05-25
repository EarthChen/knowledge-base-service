"""Tests for incremental tree rebuild and compound key assignment."""
from __future__ import annotations

import pytest
from wiki.nodes.graph_domain_decompose import _assign_changed_modules_incremental


class TestIncrementalCompoundKey:
    def test_bare_name_collision_fixed(self):
        """Cross-repo same-name modules should not inherit wrong domain."""
        existing_mod_to_domain = {
            ("repo_a", "UserService"): "auth",
            ("repo_b", "UserService"): "billing",
        }
        domain_mapping = {
            "auth": [("repo_a", "UserService")],
            "billing": [("repo_b", "UserService")],
        }
        changed_biz = [("repo_a", "UserService")]
        edges = []

        _assign_changed_modules_incremental(
            changed_biz, edges, domain_mapping, existing_mod_to_domain,
        )

        # repo_a's UserService should stay in "auth", not be moved to "billing"
        assert ("repo_a", "UserService") in domain_mapping["auth"]
        assert ("repo_a", "UserService") not in domain_mapping.get("billing", [])

    def test_fallback_to_bare_name(self):
        """When compound key not found, fall back to bare name lookup."""
        existing_mod_to_domain = {
            "OldModule": "legacy",
        }
        domain_mapping = {
            "legacy": [],
        }
        changed_biz = [("repo_x", "OldModule")]
        edges = []

        _assign_changed_modules_incremental(
            changed_biz, edges, domain_mapping, existing_mod_to_domain,
        )

        assert ("repo_x", "OldModule") in domain_mapping["legacy"]
