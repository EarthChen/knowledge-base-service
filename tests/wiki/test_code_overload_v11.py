"""Tests for F6: Overview code overload detection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.quality_gate import quality_gate_node


def _overview_page(
    *,
    path: str = "/__domains__/test/_overview",
    content: str,
    content_language: str = "简体中文",
) -> dict:
    return {
        "path": path,
        "title": "Test Overview",
        "page_type": "domain_overview",
        "content_language": content_language,
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }


def _code_blocks(count: int) -> str:
    return "".join(f"```java\npublic class Block{i} {{}}\n```\n" for i in range(count))


def _mixed_cn_overview(*, cn_ratio: float, code_block_count: int, min_len: int = 2500) -> str:
    """Build domain_overview content with approximate cn_ratio and N code blocks."""
    total = min_len
    cn_count = int(total * cn_ratio)
    en_count = total - cn_count
    body = ("中" * cn_count) + ("a" * en_count)
    return (
        "## 概述\n"
        f"{body}\n"
        "## 核心业务流程\n"
        "流程说明段落。\n"
        f"{_code_blocks(code_block_count)}"
        "## 模块详解\n"
        "### ModuleA\n"
        "模块职责说明。\n"
        "## 依赖关系\n"
        "- [[peer-module]]\n"
    )


async def _run_quality_gate(page: dict) -> dict:
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)

    with (
        patch("wiki.nodes.quality_gate.get_settings") as mock_settings,
        patch("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval),
        patch(
            "wiki.nodes.quality_gate.verify_citations",
            lambda content, names: MagicMock(invalid_count=0),
        ),
    ):
        wiki_cfg = MagicMock()
        wiki_cfg.heal_l2_threshold = 0.0
        wiki_cfg.heal_on_l3_failure = False
        wiki_cfg.heal_l3_threshold = 0.5
        wiki_cfg.overview_min_content_chars = 2000
        wiki_cfg.topic_min_content_chars = 500
        wiki_cfg.language_guardrail_cn_ratio = 0.15
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        return await quality_gate_node(state, {"configurable": {}})


@pytest.mark.asyncio
async def test_overview_code_overload_triggers_heal():
    """Overview with >5 code blocks and cn_ratio < 0.20 should trigger heal."""
    content = _mixed_cn_overview(cn_ratio=0.18, code_block_count=6)
    page = _overview_page(content=content)

    result = await _run_quality_gate(page)

    assert page["path"] in result.get("pages_to_heal", [])
    hint = result["heal_hints"].get(page["path"], "")
    assert "overview_code_overload" in hint


@pytest.mark.asyncio
async def test_overview_code_overload_high_cn_ratio_passes():
    """Overview with >5 code blocks but cn_ratio >= 0.20 should not trigger code overload."""
    content = _mixed_cn_overview(cn_ratio=0.25, code_block_count=6)
    page = _overview_page(content=content)

    result = await _run_quality_gate(page)

    hint = result["heal_hints"].get(page["path"], "")
    assert "overview_code_overload" not in hint


@pytest.mark.asyncio
async def test_overview_few_code_blocks_no_code_overload():
    """Overview with <=5 code blocks should not trigger code overload (F3 handles cn_ratio)."""
    content = _mixed_cn_overview(cn_ratio=0.18, code_block_count=5)
    page = _overview_page(content=content)

    result = await _run_quality_gate(page)

    hint = result["heal_hints"].get(page["path"], "")
    assert "overview_code_overload" not in hint


@pytest.mark.asyncio
async def test_topic_many_code_blocks_not_affected():
    """Topic page with many code blocks should not trigger overview code overload."""
    code_section = _code_blocks(8)
    english_body = (
        "This service layer coordinates authentication and authorization across modules. "
        * 40
    )
    content = (
        "## Overview\n"
        f"{english_body}\n"
        "## Key components\n"
        f"{code_section}"
        "## Relationships\n"
        "- [[peer-module]]\n"
    )
    page = {
        "path": "/wiki/code-heavy-topic",
        "title": "Code Heavy Topic",
        "page_type": "topic",
        "content_language": "en",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }

    result = await _run_quality_gate(page)

    hint = result["heal_hints"].get(page["path"], "")
    assert "overview_code_overload" not in hint
