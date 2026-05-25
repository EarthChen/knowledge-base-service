"""Tests for repo-aware edge matching in incremental module assignment."""
from __future__ import annotations

from wiki.nodes.graph_domain_decompose import _assign_changed_modules_incremental


class TestIncrementalEdgeRepoMatching:
    def test_edge_match_respects_repository(self):
        """Same module name in different repos must not inherit wrong domain via edges."""
        existing_mod_to_domain = {
            ("repo_a", "AuthHelper"): "auth",
            ("repo_b", "AuthHelper"): "billing",
        }
        domain_mapping = {
            "auth": [("repo_a", "AuthHelper")],
            "billing": [("repo_b", "AuthHelper")],
        }
        changed_biz = [("repo_a", "UserService")]
        edges = [
            (("repo_a", "UserService"), ("repo_a", "AuthHelper"), 1),
            (("repo_b", "UserService"), ("repo_b", "AuthHelper"), 1),
        ]

        _assign_changed_modules_incremental(
            changed_biz, edges, domain_mapping, existing_mod_to_domain,
        )

        assert ("repo_a", "UserService") in domain_mapping["auth"]
        assert ("repo_a", "UserService") not in domain_mapping.get("billing", [])

    def test_inbound_edge_match_respects_repository(self):
        """Inbound call edges must also match repo, not just module name."""
        existing_mod_to_domain = {
            ("repo_a", "OrderService"): "orders",
            ("repo_b", "OrderService"): "fulfillment",
        }
        domain_mapping = {
            "orders": [("repo_a", "OrderService")],
            "fulfillment": [("repo_b", "OrderService")],
        }
        changed_biz = [("repo_b", "UserService")]
        edges = [
            (("repo_a", "OrderService"), ("repo_a", "UserService"), 1),
            (("repo_b", "OrderService"), ("repo_b", "UserService"), 1),
        ]

        _assign_changed_modules_incremental(
            changed_biz, edges, domain_mapping, existing_mod_to_domain,
        )

        assert ("repo_b", "UserService") in domain_mapping["fulfillment"]
        assert ("repo_b", "UserService") not in domain_mapping.get("orders", [])
