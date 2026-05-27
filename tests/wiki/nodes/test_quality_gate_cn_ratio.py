"""Tests for Chinese character ratio quality gate on topic pages."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.quality_gate import quality_gate_node


def _topic_page(
    *,
    path: str = "/wiki/low-cn-topic",
    content: str,
    content_language: str = "简体中文",
) -> dict:
    return {
        "path": path,
        "title": "Low CN Topic",
        "page_type": "topic",
        "content_language": content_language,
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }


def _passing_structure_content(*, english_body: str) -> str:
    """Long topic body with valid L1 sections; ``english_body`` fills Overview."""
    return (
        "## Overview\n"
        f"{english_body}\n"
        "## Key components\n"
        "Core module handles requests.\n"
        "## Relationships\n"
        "- [[peer-module]]\n"
    )


@pytest.mark.asyncio
async def test_quality_gate_marks_low_cn_topic_for_heal():
    """English-dominant topic with Chinese content_language should enter heal pipeline."""
    english_body = (
        "This service layer coordinates authentication and authorization across modules. "
        * 30
    )
    page = _topic_page(content=_passing_structure_content(english_body=english_body))
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

        result = await quality_gate_node(state, {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    assert "low_cn_ratio" in (page.get("metadata") or {}).get("heal_reason", "")


@pytest.mark.asyncio
async def test_quality_gate_passes_good_cn_topic():
    """Topic with sufficient Chinese characters should not heal for language ratio."""
    chinese_body = "该模块负责处理用户认证与授权流程，并与下游服务协同。" * 80
    page = _topic_page(
        path="/wiki/good-cn-topic",
        content=_passing_structure_content(english_body=chinese_body),
    )
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

        result = await quality_gate_node(state, {"configurable": {}})

    assert page["path"] not in result.get("pages_to_heal", [])


@pytest.mark.asyncio
async def test_quality_gate_cn_ratio_auto_detect():
    """Without content_language, CN ratio check runs when content is Chinese-dominant."""
    chinese_body = "该模块负责用户认证与授权流程，并与下游服务协同完成业务处理。" * 12
    english_body = (
        "This service layer coordinates authentication and authorization across modules. "
        * 15
    )
    content = (
        "## 概述\n"
        f"{chinese_body}\n{english_body}\n"
        "## 关键组件\n"
        "Core module handles requests.\n"
        "## 关联关系\n"
        "- [[peer-module]]\n"
    )
    page = _topic_page(content=content, content_language="")
    page.pop("content_language", None)
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
        wiki_cfg.language_guardrail_cn_ratio = 0.4
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    assert "low_cn_ratio" in (page.get("metadata") or {}).get("heal_reason", "")


@pytest.mark.asyncio
async def test_quality_gate_cn_ratio_skip_english_page():
    """Pure English topic without content_language should not trigger Chinese CN ratio check."""
    english_body = (
        "This service layer coordinates authentication and authorization across modules. "
        * 40
    )
    page = _topic_page(content=_passing_structure_content(english_body=english_body))
    page.pop("content_language", None)
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
        wiki_cfg.language_guardrail_cn_ratio = 0.4
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        await quality_gate_node(state, {"configurable": {}})

    heal_reason = (page.get("metadata") or {}).get("heal_reason", "")
    assert "low_cn_ratio" not in heal_reason
