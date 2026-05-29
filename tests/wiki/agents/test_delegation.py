from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.agents.delegation import DelegationConfig, DelegationMode, DelegationResult, execute_delegation


@pytest.mark.asyncio
async def test_max_depth_exceeded_returns_error():
    deps = MagicMock()
    deps.delegation_depth = 3
    deps.delegation_count = 0
    config = DelegationConfig(max_depth=2)
    result = await execute_delegation(config, lambda d: MagicMock(), deps, task_input={})
    assert result.metadata.get("error") == "max_depth"


@pytest.mark.asyncio
async def test_max_count_exceeded_returns_error():
    deps = MagicMock()
    deps.delegation_depth = 0
    deps.delegation_count = 5
    config = DelegationConfig(max_count=3)
    result = await execute_delegation(config, lambda d: MagicMock(), deps, task_input={})
    assert result.metadata.get("error") == "max_count"


@pytest.mark.asyncio
async def test_isolated_mode_no_memory():
    deps = MagicMock()
    deps.delegation_depth = 0
    deps.delegation_count = 0

    child_agent = AsyncMock()
    child_agent.generate = AsyncMock(return_value="output")
    child_agent._current_memory = None
    child_agent._tool_call_count = 2

    config = DelegationConfig(mode=DelegationMode.ISOLATED)
    result = await execute_delegation(config, lambda d: child_agent, deps, task_input={"prompt": "test"})
    assert result.output == "output"
    assert result.delegation_depth == 1


@pytest.mark.asyncio
async def test_seeded_mode_passes_memory_seed():
    deps = MagicMock()
    deps.delegation_depth = 0
    deps.delegation_count = 0

    parent_mem = MagicMock()
    parent_mem.slice = MagicMock()
    sliced = MagicMock()
    sliced.to_prompt = MagicMock(return_value="seed data")
    parent_mem.slice.return_value = sliced

    child_agent = AsyncMock()
    child_agent.generate = AsyncMock(return_value="output")
    child_agent._current_memory = None
    child_agent._tool_call_count = 3

    config = DelegationConfig(mode=DelegationMode.SEEDED)
    result = await execute_delegation(
        config,
        lambda d: child_agent,
        deps,
        task_input={"entity_names": ["A"]},
        parent_memory=parent_mem,
    )
    assert result.output == "output"
    parent_mem.slice.assert_called_once()


@pytest.mark.asyncio
async def test_delegation_count_and_depth_increment():
    deps = MagicMock()
    deps.delegation_depth = 0
    deps.delegation_count = 2

    child_agent = AsyncMock()
    child_agent.generate = AsyncMock(return_value="ok")
    child_agent._current_memory = None
    child_agent._tool_call_count = 0

    captured = {}

    def factory(child_deps):
        captured["deps"] = child_deps
        return child_agent

    config = DelegationConfig()
    await execute_delegation(config, factory, deps, task_input={})
    assert captured["deps"].delegation_count == 3
    assert captured["deps"].delegation_depth == 1


@pytest.mark.asyncio
async def test_read_only_restricts_tools():
    deps = MagicMock()
    deps.delegation_depth = 0
    deps.delegation_count = 0

    child_agent = MagicMock()
    child_agent.generate = AsyncMock(return_value="ok")
    child_agent.restrict_tools = MagicMock()
    child_agent._current_memory = None
    child_agent._tool_call_count = 0

    config = DelegationConfig(read_only=True)
    await execute_delegation(config, lambda d: child_agent, deps, task_input={})
    child_agent.restrict_tools.assert_called_once()


def test_delegation_mode_enum():
    assert DelegationMode.ISOLATED.value == "isolated"
    assert DelegationMode.SEEDED.value == "seeded"
    assert DelegationMode.FULL.value == "full"


def test_delegation_config_defaults():
    config = DelegationConfig()
    assert config.mode == DelegationMode.SEEDED
    assert config.max_depth == 2
    assert config.max_count == 3
    assert config.read_only is False


def test_delegation_result_fields():
    result = DelegationResult(output="test", quality_score=0.8)
    assert result.output == "test"
    assert result.quality_score == 0.8
    assert result.delegation_depth == 0
    assert result.gaps == []
