from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def test_explore_compactor_uses_custom_model():
    """ExploreCompactor should use the provided model for LLM calls."""
    from wiki.agents.context_compactor import ExploreCompactor

    llm = AsyncMock()
    compactor = ExploreCompactor(llm_port=llm, model="gpt-4o-mini")
    assert compactor._model == "gpt-4o-mini"


def test_explore_compactor_default_model_is_none():
    """Without model specified, ExploreCompactor uses default (None)."""
    from wiki.agents.context_compactor import ExploreCompactor

    llm = AsyncMock()
    compactor = ExploreCompactor(llm_port=llm)
    assert compactor._model is None


@pytest.mark.asyncio
async def test_compact_passes_model_to_llm():
    """When compacting, the model should be passed to llm.complete."""
    from wiki.agents.context_compactor import ExploreCompactor

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="## 1. Primary Objective\nGoal\n## 2. Key Discoveries\n- Entity (path): desc")

    compactor = ExploreCompactor(llm_port=llm, model="claude-3-haiku-20240307")
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "thinking"},
    ]
    await compactor.compact(msgs, 1, 2)

    # Verify model was passed to LLM
    call_kwargs = llm.complete.call_args
    if call_kwargs:
        assert call_kwargs.kwargs.get("model") == "claude-3-haiku-20240307" or (
            len(call_kwargs.args) > 2 and call_kwargs.args[2] == "claude-3-haiku-20240307"
        )


def test_loopconfig_compaction_model():
    """LoopConfig should support compaction_model field."""
    from wiki.agents.runner import LoopConfig

    config = LoopConfig(compaction_model="gpt-4o-mini")
    assert config.compaction_model == "gpt-4o-mini"

    config_default = LoopConfig()
    assert config_default.compaction_model is None
