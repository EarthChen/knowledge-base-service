# tests/wiki/test_parent_cross_domain.py
"""Tests for P1.5: parent domain aggregation cross-domain call helper."""

from __future__ import annotations

from wiki.pipeline_nodes import _build_subdomain_interactions


class TestBuildSubdomainInteractions:
    def test_builds_interaction_text_from_metadata(self):
        child_pages = [
            {
                "title": "Payment Processing",
                "metadata": {
                    "domain_name": "Payment",
                    "cross_domain_calls": [
                        {"from": "PaymentService", "to": "NotificationService", "to_domain": "Notification"},
                        {"from": "PaymentService", "to": "OrderService", "to_domain": "Order"},
                    ],
                },
            },
            {
                "title": "Order Management",
                "metadata": {
                    "domain_name": "Order",
                    "cross_domain_calls": [
                        {"from": "OrderService", "to": "PaymentService", "to_domain": "Payment"},
                    ],
                },
            },
        ]

        result = _build_subdomain_interactions(child_pages)
        assert isinstance(result, str)
        assert "Sub-domain Interactions" in result
        assert "Payment" in result
        assert "Notification" in result
        assert "Order" in result

    def test_empty_when_no_cross_domain_calls(self):
        child_pages = [
            {"title": "Isolated", "metadata": {"domain_name": "Isolated", "cross_domain_calls": []}},
        ]
        result = _build_subdomain_interactions(child_pages)
        assert result == ""

    def test_empty_when_no_metadata(self):
        child_pages = [
            {"title": "NoMeta", "metadata": {}},
            {"title": "NoMeta2"},
        ]
        result = _build_subdomain_interactions(child_pages)
        assert result == ""

    def test_empty_pages_list(self):
        result = _build_subdomain_interactions([])
        assert result == ""

    def test_deduplicates_targets(self):
        """Multiple calls to the same target module should not repeat."""
        child_pages = [
            {
                "title": "Payment",
                "metadata": {
                    "domain_name": "Payment",
                    "cross_domain_calls": [
                        {"from": "PaySvc", "to": "NotifySvc", "to_domain": "Notification"},
                        {"from": "PaySvc", "to": "NotifySvc", "to_domain": "Notification"},
                        {"from": "PaySvc", "to": "NotifySvc", "to_domain": "Notification"},
                    ],
                },
            },
        ]
        result = _build_subdomain_interactions(child_pages)
        assert result.count("NotifySvc") == 1

    def test_limits_output_items(self):
        """Should not produce excessive output for many interactions."""
        calls = [{"from": f"Svc{i}", "to": f"Target{i}", "to_domain": f"Domain{i}"} for i in range(30)]
        child_pages = [
            {"title": "Busy", "metadata": {"domain_name": "Busy", "cross_domain_calls": calls}},
        ]
        result = _build_subdomain_interactions(child_pages)
        lines = [line for line in result.split("\n") if line.startswith("- ")]
        assert len(lines) <= 20

    def test_handles_missing_fields_gracefully(self):
        """Incomplete call dicts should not crash."""
        child_pages = [
            {
                "title": "Partial",
                "metadata": {
                    "domain_name": "Partial",
                    "cross_domain_calls": [
                        {"from": "Svc1"},  # missing to/to_domain
                        {"to": "Svc2", "to_domain": "Other"},  # missing from
                    ],
                },
            },
        ]
        result = _build_subdomain_interactions(child_pages)
        # Should not crash
        assert isinstance(result, str)
