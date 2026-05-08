# tests/wiki/test_ccb_agent_context.py
"""Tests for EnrichedDomainContext.format_summary_for_agent() — P1.3."""

from __future__ import annotations

from wiki.content_context_builder import (
    CallChainStep,
    EnrichedDomainContext,
    EntityDetail,
    MethodDetail,
)


class TestFormatSummaryForAgent:
    def _make_context(self) -> EnrichedDomainContext:
        return EnrichedDomainContext(
            domain_name="Payment",
            parent_domain="Commerce",
            biz_entities=[
                EntityDetail(
                    uid="Module::PaymentService:0",
                    name="PaymentService",
                    repository="payment-repo",
                    file_path="src/service/PaymentService.java",
                    entity_type="Module",
                    business_summary="Handles payment processing",
                    methods=[
                        MethodDetail(
                            name="processPayment",
                            signature="public PaymentResult processPayment(PaymentRequest req)",
                            file_path="src/service/PaymentService.java",
                            start_line=45,
                            repository="payment-repo",
                        ),
                        MethodDetail(
                            name="refund",
                            signature="public void refund(String orderId)",
                            file_path="src/service/PaymentService.java",
                            start_line=120,
                            repository="payment-repo",
                        ),
                    ],
                ),
            ],
            cross_domain_calls=[
                CallChainStep(
                    caller="PaymentService",
                    callee="NotificationService",
                    caller_method="processPayment",
                    callee_method="sendReceipt",
                    relationship="CALLS",
                ),
            ],
            interface_impls=[
                {"interface": "PaymentGateway", "impl": "StripeGateway", "module": "PaymentService"}
            ],
            external_callers=[
                {"caller": "OrderService", "method": "checkout", "target": "PaymentService.processPayment"}
            ],
        )

    def test_returns_non_empty_string(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_contains_method_signatures(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "processPayment" in summary
        assert "refund" in summary

    def test_contains_cross_domain_calls(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "NotificationService" in summary

    def test_contains_interface_impls(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "PaymentGateway" in summary or "StripeGateway" in summary

    def test_contains_external_callers(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent()
        assert "OrderService" in summary

    def test_respects_max_length(self):
        ctx = self._make_context()
        summary = ctx.format_summary_for_agent(max_chars=200)
        assert len(summary) <= 200

    def test_empty_context_returns_minimal_summary(self):
        ctx = EnrichedDomainContext(domain_name="Empty", parent_domain="Root")
        summary = ctx.format_summary_for_agent()
        assert isinstance(summary, str)
        assert summary == ""
