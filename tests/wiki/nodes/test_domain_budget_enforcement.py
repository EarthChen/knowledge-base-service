"""Tests for domain budget enforcement after decomposition."""
from __future__ import annotations

import pytest


class TestEnforceDomainBudget:
    def test_under_budget_no_change(self):
        """Domains under budget should not be merged."""
        from wiki.nodes.graph_domain_decompose import _enforce_domain_budget

        domain_mapping = {f"domain-{i}": [("repo", f"Mod{i}")] for i in range(10)}
        display_names = {f"domain-{i}": f"域{i}" for i in range(10)}

        new_mapping, new_display = _enforce_domain_budget(
            domain_mapping, display_names, budget=50,
        )
        assert len(new_mapping) == 10

    def test_over_budget_merges_smallest(self):
        """When over budget, smallest domains should be merged into neighbors."""
        from wiki.nodes.graph_domain_decompose import _enforce_domain_budget

        domain_mapping = {}
        display_names = {}
        for i in range(60):
            domain_mapping[f"domain-{i}"] = [("repo", f"Mod{i}")]
            display_names[f"domain-{i}"] = f"域{i}"
        domain_mapping["domain-0"] = [("repo", f"Mod0-{j}") for j in range(5)]

        new_mapping, new_display = _enforce_domain_budget(
            domain_mapping, display_names, budget=50,
        )
        assert len(new_mapping) <= 50

    def test_modules_not_lost(self):
        """After budget enforcement, total module count must be preserved."""
        from wiki.nodes.graph_domain_decompose import _enforce_domain_budget

        domain_mapping = {f"domain-{i}": [("repo", f"Mod{i}")] for i in range(60)}
        display_names = {f"domain-{i}": f"域{i}" for i in range(60)}

        original_modules = sum(len(v) for v in domain_mapping.values())
        new_mapping, new_display = _enforce_domain_budget(
            domain_mapping, display_names, budget=50,
        )
        new_modules = sum(len(v) for v in new_mapping.values())
        assert new_modules == original_modules
