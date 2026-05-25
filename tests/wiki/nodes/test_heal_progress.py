"""Tests for fine-grained progress updates in heal_pages_node."""

from __future__ import annotations

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
        "heal_max_rounds_core": 2,
        "heal_max_rounds_standard": 1,
    }
    defaults.update(overrides)
    return patch("core.config.get_settings")


@pytest.mark.asyncio
async def test_heal_pages_reports_progress_with_correct_phase() -> None:
    """Progress callback receives heal_pages phase on triage and tier rounds."""
    progress_calls: list[dict[str, Any]] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        progress_calls.append(payload)

    core_path = "/__domains__/d/core/_topic"
    std_path = "/__domains__/d/std/_topic"
    pages = [
        _make_page(core_path),
        _make_page(std_path),
    ]
    state = {
        "pages_to_heal": [core_path, std_path],
        "pages": pages,
        "config": {
            "importance_tiers": {
                core_path: "core",
                std_path: "standard",
            },
        },
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [],
    }

    async def mock_heal_one_page(**kwargs: object) -> bool:
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

    with _mock_settings() as mock_settings:
        mock_settings.return_value.wiki.heal_concurrency = 5
        mock_settings.return_value.wiki.heal_max_rounds_core = 2
        mock_settings.return_value.wiki.heal_max_rounds_standard = 1
        with patch("wiki.nodes.heal._heal_one_page", side_effect=mock_heal_one_page):
            await heal_pages_node(
                state,
                {"configurable": {"llm": AsyncMock(), "progress_callback": on_progress}},
            )

    assert progress_calls, "expected at least one progress update"
    for call in progress_calls:
        assert call["phase"] == "heal_pages"
        assert "detail" in call
        assert isinstance(call["progress_pct"], float)


@pytest.mark.asyncio
async def test_heal_progress_pct_stays_within_node_range() -> None:
    """Intra-node progress_pct should interpolate within 0.80–0.89."""
    progress_calls: list[dict[str, Any]] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        progress_calls.append(payload)

    pages = [_make_page(f"/__domains__/d/p{i}/_topic") for i in range(3)]
    state = {
        "pages_to_heal": [p["path"] for p in pages],
        "pages": pages,
        "config": {"importance_tiers": {p["path"]: "core" for p in pages}},
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [],
    }

    with _mock_settings() as mock_settings:
        mock_settings.return_value.wiki.heal_concurrency = 5
        mock_settings.return_value.wiki.heal_max_rounds_core = 3
        mock_settings.return_value.wiki.heal_max_rounds_standard = 1
        with patch("wiki.nodes.heal._heal_one_page", return_value=False):
            await heal_pages_node(
                state,
                {"configurable": {"llm": AsyncMock(), "progress_callback": on_progress}},
            )

    pcts = [c["progress_pct"] for c in progress_calls]
    assert min(pcts) >= 0.80
    assert max(pcts) <= 0.89


@pytest.mark.asyncio
async def test_heal_progress_callback_count_and_milestones() -> None:
    """Verify triage, per-round, and tier-completion progress updates."""
    progress_calls: list[dict[str, Any]] = []

    async def on_progress(payload: dict[str, Any]) -> None:
        progress_calls.append(payload)

    core_path = "/__domains__/d/core/_topic"
    pages = [_make_page(core_path)]
    state = {
        "pages_to_heal": [core_path],
        "pages": pages,
        "config": {"importance_tiers": {core_path: "core"}},
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [],
    }

    with _mock_settings() as mock_settings:
        mock_settings.return_value.wiki.heal_concurrency = 5
        mock_settings.return_value.wiki.heal_max_rounds_core = 2
        mock_settings.return_value.wiki.heal_max_rounds_standard = 1
        with patch("wiki.nodes.heal._heal_one_page", return_value=False):
            await heal_pages_node(
                state,
                {"configurable": {"llm": AsyncMock(), "progress_callback": on_progress}},
            )

    details = [c["detail"] for c in progress_calls]
    assert any("core + 0 standard" in d for d in details)
    assert any("core: round 1/2" in d for d in details)
    assert any("core pages done" in d for d in details)
    assert any("standard pages done" in d for d in details)
    assert len(progress_calls) >= 4


@pytest.mark.asyncio
async def test_heal_progress_callback_errors_are_swallowed() -> None:
    """Progress callback failures must not abort healing."""

    async def failing_callback(_payload: dict[str, Any]) -> None:
        raise RuntimeError("callback boom")

    pages = [_make_page("/__domains__/d/p/_topic")]
    state = {
        "pages_to_heal": [pages[0]["path"]],
        "pages": pages,
        "config": {"importance_tiers": {pages[0]["path"]: "standard"}},
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [],
    }

    with _mock_settings() as mock_settings:
        mock_settings.return_value.wiki.heal_concurrency = 5
        mock_settings.return_value.wiki.heal_max_rounds_core = 2
        mock_settings.return_value.wiki.heal_max_rounds_standard = 1
        with patch("wiki.nodes.heal._heal_one_page", return_value=False):
            result = await heal_pages_node(
                state,
                {"configurable": {"llm": AsyncMock(), "progress_callback": failing_callback}},
            )

    assert result["pages_to_heal"] == []
