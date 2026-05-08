# tests/wiki/test_domain_stabilizer_batch_dedup.py
"""Tests for intra-batch deduplication in DomainStabilizer.stabilize_sync()."""

from __future__ import annotations

from wiki.domain_stabilizer import DomainStabilizer


class TestBatchDeduplication:
    """P0.2 Sub-A: When no existing domains match, near-duplicate proposed
    domains within the same batch should be merged to the first canonical."""

    def test_two_similar_proposed_merge_to_first(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["订单处理", "订单管理"],
            existing_domains=[],
        )
        assert result["订单处理"] == "订单处理"
        assert result["订单管理"] == "订单处理"

    def test_three_similar_proposed_all_merge_to_first(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Payment Service", "Payment Module", "Payment System"],
            existing_domains=[],
        )
        assert result["Payment Service"] == "Payment Service"
        assert result["Payment Module"] == "Payment Service"
        assert result["Payment System"] == "Payment Service"

    def test_dissimilar_proposed_remain_independent(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Meeting", "Payment", "User Auth"],
            existing_domains=[],
        )
        assert result["Meeting"] == "Meeting"
        assert result["Payment"] == "Payment"
        assert result["User Auth"] == "User Auth"

    def test_existing_match_takes_priority_over_batch(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["订单处理", "订单管理"],
            existing_domains=["订单"],
        )
        assert result["订单处理"] == "订单"
        assert result["订单管理"] == "订单"

    def test_batch_dedup_respects_tier_order(self):
        """First proposed domain becomes canonical (input order = priority)."""
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Live Streaming", "Live Broadcasting"],
            existing_domains=[],
        )
        assert result["Live Streaming"] == "Live Streaming"
        assert result["Live Broadcasting"] == "Live Streaming"

    def test_empty_proposed_returns_empty(self):
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(proposed_domains=[], existing_domains=[])
        assert result == {}

    def test_mixed_existing_and_batch_dedup(self):
        """Some proposed match existing, others deduplicate within batch."""
        ds = DomainStabilizer(similarity_threshold=0.8)
        result = ds.stabilize_sync(
            proposed_domains=["Meeting Management", "支付服务", "支付模块"],
            existing_domains=["Meeting"],
        )
        assert result["Meeting Management"] == "Meeting"
        assert result["支付服务"] == "支付服务"
        assert result["支付模块"] == "支付服务"
