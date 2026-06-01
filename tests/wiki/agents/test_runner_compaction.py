from __future__ import annotations

from unittest.mock import MagicMock

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


@pytest.mark.asyncio
async def test_l4_working_memory_fallback():
    """When level>=4, messages should be replaced with WorkingMemory prompt."""
    from wiki.agents.runner import LoopConfig, _apply_context_compression

    config = LoopConfig(enable_compaction=True)
    # Small effective limit (5000 - 4000 reserve) forces L4 at high usage
    budget_mgr = TokenBudgetManager(model_context_limit=5000, chars_per_token=1.0)

    memory = MagicMock()
    memory.to_prompt = MagicMock(return_value="memory context here")

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {"role": "tool", "content": "x" * 1000},
    ]

    result = await _apply_context_compression(
        msgs,
        budget_mgr=budget_mgr,
        compactor=None,
        memory=memory,
        config=config,
        _last_compact_round=[],
        round_num=1,
    )

    # L4 should produce [system, memory_prompt]
    assert len(result) == 2
    assert result[0]["role"] == "system"
    content = result[1].get("content", "")
    assert "memory context" in content.lower() or "WorkingMemory" in content


@pytest.mark.asyncio
async def test_custom_compaction_trigger_ratio_triggers_l3_earlier():
    """compaction_trigger_ratio=0.60 should promote to L3 before default 0.75."""
    from wiki.agents.runner import LoopConfig, _apply_context_compression

    config = LoopConfig(enable_compaction=True, compaction_trigger_ratio=0.60)
    budget_mgr = TokenBudgetManager(
        model_context_limit=10_000,
        chars_per_token=1.0,
        reserve_for_output=0,
        compaction_trigger_ratio=0.60,
    )
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {"role": "tool", "content": "x" * 6500},
    ]
    snap = budget_mgr.snapshot(msgs)
    assert snap.usage_ratio >= 0.60
    assert snap.usage_ratio < 0.75
    assert snap.recommended_level >= 3

    result = await _apply_context_compression(
        msgs,
        budget_mgr=budget_mgr,
        compactor=None,
        memory=None,
        config=config,
        _last_compact_round=[],
        round_num=1,
    )
    # L3 without compactor falls back to snip_compact (still mutates/truncates tool content)
    assert result is not msgs or any(
        len(m.get("content", "")) < len(msgs[i].get("content", ""))
        for i, m in enumerate(result)
        if m.get("role") == "tool"
    )
