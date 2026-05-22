"""Tests for P3.10: multi-round heal loop."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wiki.nodes.heal import _MAX_HEAL_ROUNDS, heal_pages_node


class TestMaxHealRoundsConstant:
    def test_max_rounds_is_3(self) -> None:
        assert _MAX_HEAL_ROUNDS == 3


_HEAL_GOOD_MARKDOWN = (
    "## Overview\nDetailed description of the business domain and responsibilities.\n\n"
    "## Key components\n- CoreService — handles primary workflows\n- Helper — utility operations\n\n"
    "## Relationships\n- Depends on downstream APIs; invoked by upstream controllers.\n\n"
    "```mermaid\nsequenceDiagram\nA->>B: process\n```\n\n"
    "## 业务概述\nDetailed Chinese summary of the business domain.\n\n"
    "## 核心业务流程\nOperational flow description.\n\n"
    "## 核心服务详情\n### Service\nHandles core business logic with multiple APIs.\n\n"
    "## 关联主题\n- [[other-domain]]\n"
)


def _page(short: bool = True) -> dict:
    body = "## Overview\nx\n" if short else _HEAL_GOOD_MARKDOWN
    return {
        "title": "Svc",
        "path": "wiki/multi-round-test",
        "content": body,
        "page_type": "topic",
        "domain": "test-domain",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }


@pytest.mark.asyncio
async def test_multi_round_healing_improves_until_quality_passes() -> None:
    """Second round produces passing content; LLM is invoked twice (two heal rounds)."""
    gen_calls = {"n": 0}

    async def mock_generate(prompt: str, system: str = "", **kwargs: object) -> str:
        gen_calls["n"] += 1
        if gen_calls["n"] == 1:
            return "## Overview\nstill missing sections.\n"
        return _HEAL_GOOD_MARKDOWN

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(return_value={"patches": []})
    mock_llm.generate = AsyncMock(side_effect=mock_generate)

    state = {
        "pages": [_page()],
        "pages_to_heal": ["wiki/multi-round-test"],
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [{"name": "test-domain", "modules": ["M1"], "children": []}],
        "config": {"importance_tiers": {"wiki/multi-round-test": "core"}},
    }
    result = await heal_pages_node(state, {"configurable": {"llm": mock_llm}})

    assert gen_calls["n"] == 2
    assert result["heal_attempts"]["wiki/multi-round-test"] == 2
    assert result["pages"]


@pytest.mark.asyncio
async def test_early_exit_when_quality_passes_first_round() -> None:
    gen_calls = {"n": 0}

    async def mock_generate(prompt: str, system: str = "", **kwargs: object) -> str:
        gen_calls["n"] += 1
        return _HEAL_GOOD_MARKDOWN

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(return_value={"patches": []})
    mock_llm.generate = AsyncMock(side_effect=mock_generate)

    state = {
        "pages": [_page()],
        "pages_to_heal": ["wiki/multi-round-test"],
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [],
        "config": {"importance_tiers": {"wiki/multi-round-test": "core"}},
    }
    await heal_pages_node(state, {"configurable": {"llm": mock_llm}})

    assert gen_calls["n"] == 1


@pytest.mark.asyncio
async def test_respects_max_three_rounds_when_quality_never_passes() -> None:
    bad = "## Overview\nnever passes structural threshold alone.\n"

    async def mock_generate(prompt: str, system: str = "", **kwargs: object) -> str:
        return bad

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(return_value={"patches": []})
    mock_llm.generate = AsyncMock(side_effect=mock_generate)

    state = {
        "pages": [_page()],
        "pages_to_heal": ["wiki/multi-round-test"],
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [],
        "config": {"importance_tiers": {"wiki/multi-round-test": "core"}},
    }
    result = await heal_pages_node(state, {"configurable": {"llm": mock_llm}})

    assert mock_llm.generate.call_count == _MAX_HEAL_ROUNDS
    assert result["heal_attempts"]["wiki/multi-round-test"] == _MAX_HEAL_ROUNDS


@pytest.mark.asyncio
async def test_empty_pages_to_heal_returns_early() -> None:
    state = {
        "pages": [_page()],
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
    }
    result = await heal_pages_node(state, None)

    assert result["pages"] == []
    assert result["heal_attempts"] == {}
    assert result["pages_to_heal"] == []
