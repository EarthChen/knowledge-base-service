from __future__ import annotations

from wiki.agents.token_budget import BudgetSnapshot, TokenBudgetManager


class TestTokenBudgetManager:
    def setup_method(self):
        self.mgr = TokenBudgetManager(model_context_limit=128_000, chars_per_token=3.5, reserve_for_output=4_000)

    def test_snapshot_low_usage_level_0(self):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u" * 1000}]
        snap = self.mgr.snapshot(msgs)
        assert snap.recommended_level == 0
        assert snap.usage_ratio < 0.50

    def test_snapshot_medium_usage_level_1(self):
        limit_chars = int((128_000 - 4_000) * 3.5)  # ~434K
        half_chars = int(limit_chars * 0.55)
        msgs = [{"role": "system", "content": "s"}]
        # Add tool messages that are clearable
        for i in range(5):
            msgs.append({"role": "tool", "content": "x" * (half_chars // 5)})
        snap = self.mgr.snapshot(msgs)
        assert snap.usage_ratio > 0.50
        assert snap.recommended_level >= 1

    def test_snapshot_high_usage_level_3(self):
        limit_chars = int((128_000 - 4_000) * 3.5)
        high_chars = int(limit_chars * 0.80)
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "x" * high_chars}]
        snap = self.mgr.snapshot(msgs)
        assert snap.usage_ratio > 0.75
        assert snap.recommended_level >= 3

    def test_snapshot_critical_usage_level_4(self):
        limit_chars = int((128_000 - 4_000) * 3.5)
        critical_chars = int(limit_chars * 0.97)
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "x" * critical_chars}]
        snap = self.mgr.snapshot(msgs)
        assert snap.usage_ratio > 0.95
        assert snap.recommended_level == 4

    def test_count_clearable_tool_chars(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "tool", "content": "old_result " * 5000},
            {"role": "tool", "content": "recent1"},
            {"role": "tool", "content": "recent2"},
            {"role": "tool", "content": "recent3"},
        ]
        clearable = self.mgr.count_clearable_tool_chars(msgs, keep_recent_n=3)
        assert clearable > 50_000

    def test_count_clearable_fewer_than_keep(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "tool", "content": "only_one"},
        ]
        clearable = self.mgr.count_clearable_tool_chars(msgs, keep_recent_n=3)
        assert clearable == 0

    def test_empty_messages(self):
        snap = self.mgr.snapshot([])
        assert snap.recommended_level == 0
        assert snap.total_chars == 0

    def test_snapshot_fields(self):
        msgs = [{"role": "system", "content": "hello"}]
        snap = self.mgr.snapshot(msgs)
        assert isinstance(snap, BudgetSnapshot)
        assert snap.total_chars == 5
        assert snap.estimated_tokens > 0
        assert snap.model_limit > 0
