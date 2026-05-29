from __future__ import annotations

import pytest

from wiki.agents.token_budget import TokenBudgetManager


def test_compression_level_0_for_small_context():
    mgr = TokenBudgetManager(model_context_limit=10_000, chars_per_token=1.0)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert mgr.snapshot(msgs).recommended_level == 0


def test_compression_level_increases_with_usage():
    mgr = TokenBudgetManager(model_context_limit=10_000, chars_per_token=1.0)
    msgs = [{"role": "system", "content": "s"}, {"role": "tool", "content": "x" * 6000}]
    snap = mgr.snapshot(msgs)
    assert snap.recommended_level >= 1


def test_loopconfig_has_compaction_fields():
    from wiki.agents.runner import LoopConfig

    config = LoopConfig()
    assert config.enable_compaction is False
    assert config.compaction_interval == 10
    assert config.compaction_keep_recent == 3
    assert config.micro_compact_tool_threshold == 20_000


def test_loopconfig_compaction_enabled():
    from wiki.agents.runner import LoopConfig

    config = LoopConfig(enable_compaction=True, compaction_model="gpt-4o-mini")
    assert config.enable_compaction is True
    assert config.compaction_model == "gpt-4o-mini"
