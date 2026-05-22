"""Tests for redesigned concurrent heal_pages_node."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from wiki.nodes.heal import heal_pages_node

_DEFAULT_CONTENT = "## 业务概述\nTest content with enough length to pass basic checks." * 5


def _make_page(path: str, content: str = _DEFAULT_CONTENT) -> dict[str, Any]:
    return {
        "path": path,
        "title": path.split("/")[-1],
        "content": content,
        "page_type": "topic",
        "domain": "test-domain",
    }


def _mock_settings(**overrides: int) -> patch:
    defaults = {
        "heal_concurrency": 5,
        "heal_max_rounds_core": 3,
        "heal_max_rounds_standard": 1,
    }
    defaults.update(overrides)

    return patch("core.config.get_settings")


class TestHealConcurrency:
    @pytest.mark.asyncio
    async def test_heal_runs_concurrently(self) -> None:
        """Verify heal operations run in parallel, not sequentially."""
        call_times: list[float] = []

        async def mock_heal_one_page(**kwargs: object) -> bool:
            import time

            call_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            page_dict = kwargs["page_dict"]
            assert isinstance(page_dict, dict)
            page_dict["content"] = (
                "## Overview\nDetailed description of the business domain and responsibilities.\n\n"
                "## Key components\n- CoreService — handles primary workflows\n\n"
                "## Relationships\n- Depends on downstream APIs.\n\n"
                "```mermaid\nsequenceDiagram\nA->>B: process\n```\n\n"
                "## 业务概述\nDetailed Chinese summary.\n\n"
                "## 核心业务流程\nOperational flow.\n\n"
                "## 核心服务详情\n### Service\nHandles core logic.\n\n"
                "## 关联主题\n- [[other-domain]]\n"
            )
            return True

        pages = [_make_page(f"/__domains__/d/page{i}/_topic") for i in range(5)]
        state = {
            "pages_to_heal": [p["path"] for p in pages],
            "pages": pages,
            "config": {"importance_tiers": {p["path"]: "standard" for p in pages}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [{"name": "test-domain", "modules": ["mod1"]}],
        }

        with _mock_settings() as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            with patch("wiki.nodes.heal._heal_one_page", side_effect=mock_heal_one_page):
                await heal_pages_node(state, {"configurable": {"llm": AsyncMock(), "graph_store": None}})

        assert len(call_times) >= 2
        time_spread = call_times[-1] - call_times[0]
        assert time_spread < 0.2, f"Calls should overlap (spread={time_spread}s)"


class TestHealTierStrategy:
    @pytest.mark.asyncio
    async def test_skeleton_pages_skipped(self) -> None:
        """SKELETON tier pages should not be healed."""
        mock_llm = AsyncMock()
        pages = [_make_page("/__domains__/d/skel/_topic")]
        state = {
            "pages_to_heal": [pages[0]["path"]],
            "pages": pages,
            "config": {"importance_tiers": {pages[0]["path"]: "skeleton"}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [],
        }

        with _mock_settings() as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            result = await heal_pages_node(state, {"configurable": {"llm": mock_llm, "graph_store": None}})

        mock_llm.generate.assert_not_called()
        assert result["pages"] == []
        assert result["heal_attempts"] == {}

    @pytest.mark.asyncio
    async def test_standard_pages_one_round_only(self) -> None:
        """STANDARD tier pages get exactly 1 heal round."""
        heal_call_count = 0

        async def counting_generate(*args: object, **kwargs: object) -> str:
            nonlocal heal_call_count
            heal_call_count += 1
            return "Short"

        mock_llm = AsyncMock()
        mock_llm.generate = counting_generate
        mock_llm.complete_json = AsyncMock(return_value=None)

        pages = [_make_page(f"/__domains__/d/std{i}/_topic") for i in range(3)]
        state = {
            "pages_to_heal": [p["path"] for p in pages],
            "pages": pages,
            "config": {"importance_tiers": {p["path"]: "standard" for p in pages}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [{"name": "test-domain", "modules": ["mod1"]}],
        }

        with _mock_settings() as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            await heal_pages_node(state, {"configurable": {"llm": mock_llm, "graph_store": None}})

        assert heal_call_count == 3

    @pytest.mark.asyncio
    async def test_core_pages_multiple_rounds_when_failing(self) -> None:
        """CORE tier pages retry up to heal_max_rounds_core when quality threshold not met."""
        heal_calls: dict[str, int] = {}

        async def mock_heal_one_page(**kwargs: object) -> bool:
            page_path = str(kwargs["page_path"])
            heal_calls[page_path] = heal_calls.get(page_path, 0) + 1
            page_dict = kwargs["page_dict"]
            assert isinstance(page_dict, dict)
            if heal_calls[page_path] >= 2:
                page_dict["content"] = (
                    "## Overview\nDetailed description of the business domain and responsibilities.\n\n"
                    "## Key components\n- CoreService — handles primary workflows\n\n"
                    "## Relationships\n- Depends on downstream APIs.\n\n"
                    "```mermaid\nsequenceDiagram\nA->>B: process\n```\n\n"
                    "## 业务概述\nDetailed Chinese summary.\n\n"
                    "## 核心业务流程\nOperational flow.\n\n"
                    "## 核心服务详情\n### Service\nHandles core logic.\n\n"
                    "## 关联主题\n- [[other-domain]]\n"
                )
            else:
                page_dict["content"] = "## Overview\nstill failing.\n"
            return True

        page_path = "/__domains__/d/core/_topic"
        pages = [_make_page(page_path, content="## Overview\nbad.\n")]
        state = {
            "pages_to_heal": [page_path],
            "pages": pages,
            "config": {"importance_tiers": {page_path: "core"}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [],
        }

        with _mock_settings() as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            with patch("wiki.nodes.heal._heal_one_page", side_effect=mock_heal_one_page):
                result = await heal_pages_node(
                    state,
                    {"configurable": {"llm": AsyncMock(), "graph_store": None}},
                )

        assert heal_calls[page_path] == 2
        assert result["pages"]


class TestHealNoLLM:
    @pytest.mark.asyncio
    async def test_no_llm_graceful_degradation(self) -> None:
        """Without LLM, heal should still update hints and return gracefully."""
        pages = [_make_page("/__domains__/d/p/_topic")]
        state = {
            "pages_to_heal": [pages[0]["path"]],
            "pages": pages,
            "config": {"importance_tiers": {}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [],
        }

        with _mock_settings() as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            result = await heal_pages_node(state, {"configurable": {"llm": None, "graph_store": None}})

        assert result["pages_to_heal"] == []
        assert pages[0]["path"] in result["heal_hints"]
