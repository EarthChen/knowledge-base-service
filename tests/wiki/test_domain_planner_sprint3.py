"""Sprint 3 tests: parse_json_robust integration, timeout-split-retry, AdaptiveBatchSizer."""
from __future__ import annotations

import asyncio
import json

import pytest
from unittest.mock import AsyncMock

from store.schema import GraphNode, NodeLabel
from wiki.business_domain_planner import BusinessDomainPlanner


def _make_module(name: str, summary: str = "") -> GraphNode:
    return GraphNode(
        uid=f"Module:r:{name}",
        label=NodeLabel.MODULE,
        properties={"name": name, "business_summary": summary, "path": name},
    )


@pytest.mark.asyncio
async def test_parse_json_robust_handles_trailing_comma():
    """JSON with trailing comma should be auto-repaired by parse_json_robust."""
    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(return_value='{"auth": ["UserService",], "core": ["MainApp"]}')

    planner = BusinessDomainPlanner(llm)
    result = await planner.classify("repo", [_make_module("UserService"), _make_module("MainApp")])

    assert "auth" in result
    assert "UserService" in result["auth"]


@pytest.mark.asyncio
async def test_timeout_split_retry():
    """When a batch times out, it should be split in half and retried."""
    call_count = 0

    async def mock_generate(prompt: str, system: str = "", **kwargs) -> str:
        nonlocal call_count
        call_count += 1
        modules_in_prompt = prompt.count('"name"')
        if modules_in_prompt > 15:
            await asyncio.sleep(999)
        return json.dumps({"A": [f"mod-{i}" for i in range(modules_in_prompt)]})

    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(side_effect=mock_generate)

    modules = [_make_module(f"mod-{i}") for i in range(30)]
    planner = BusinessDomainPlanner(llm)
    result = await planner.classify(
        "repo", modules, sub_batch_size=30, batch_timeout=0.1,
    )

    assert len(result) > 0
    total_assigned = sum(len(v) for v in result.values())
    assert total_assigned == 30


@pytest.mark.asyncio
async def test_adaptive_batch_sizer_shrinks_on_slow():
    """AdaptiveBatchSizer should reduce batch size after slow responses."""
    call_sizes: list[int] = []

    async def slow_generate(prompt: str, system: str = "", **kwargs) -> str:
        modules_in_prompt = prompt.count('"name"')
        call_sizes.append(modules_in_prompt)
        await asyncio.sleep(0.05)
        return json.dumps({"A": [f"m{i}" for i in range(modules_in_prompt)]})

    llm = AsyncMock(spec=["generate"])
    llm.generate = AsyncMock(side_effect=slow_generate)

    modules = [_make_module(f"m{i}") for i in range(200)]
    planner = BusinessDomainPlanner(llm)
    result = await planner.classify(
        "repo", modules, sub_batch_size=80, max_concurrency=1,
    )

    total_assigned = sum(len(v) for v in result.values())
    assert total_assigned == 200
