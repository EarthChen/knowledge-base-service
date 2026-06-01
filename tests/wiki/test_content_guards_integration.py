"""Integration tests for wiki.content_guards in quality_gate, finalize, and page_agent."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.finalize import _sanitize_published_content, finalize_node
from wiki.nodes.quality_gate import quality_gate_node
from wiki.page_agent import strip_agent_artifacts


def _passing_structure_content(*, body: str) -> str:
    return (
        "## Overview\n"
        f"{body}\n"
        "## Key components\n"
        "Core module handles requests.\n"
        "## Relationships\n"
        "- [[peer-module]]\n"
    )


def _topic_page(
    *,
    path: str,
    content: str,
    content_language: str = "简体中文",
) -> dict:
    return {
        "path": path,
        "title": "Test Topic",
        "page_type": "topic",
        "content_language": content_language,
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }


def _quality_gate_state(page: dict) -> dict:
    return {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }


@pytest.mark.asyncio
async def test_quality_gate_detects_hallucination():
    """Page with fabricated SLA should enter heal pipeline via hard reject."""
    body = (
        "该模块负责用户认证。系统响应时间 SLA < 200ms，P99 < 500ms，可用性 99.999%。"
        * 20
    )
    page = _topic_page(
        path="/wiki/hallucinated-topic",
        content=_passing_structure_content(body=body),
    )

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

        result = await quality_gate_node(_quality_gate_state(page), {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "SLA" in hint or "hallucination" in hint.lower()


@pytest.mark.asyncio
async def test_quality_gate_detects_boilerplate():
    """Page with multiple boilerplate phrases should enter heal pipeline."""
    body = (
        "该模块遵循高内聚低耦合的分层架构设计，显著提升了系统的可维护性和可扩展性。"
        * 15
    )
    page = _topic_page(
        path="/wiki/boilerplate-topic",
        content=_passing_structure_content(body=body),
    )

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

        result = await quality_gate_node(_quality_gate_state(page), {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "boilerplate" in hint


@pytest.mark.asyncio
async def test_quality_gate_detects_meta_sections():
    """Page with LLM meta sections should enter heal pipeline."""
    body = "该模块负责用户认证与授权流程，并与下游服务协同完成业务处理。" * 20
    content = _passing_structure_content(body=body) + "\n## 改进建议\n\n建议补充更多测试用例。\n"
    page = _topic_page(path="/wiki/meta-section-topic", content=content)

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

        result = await quality_gate_node(_quality_gate_state(page), {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "meta" in hint.lower()


def test_finalize_strips_meta_sections():
    content = "## 概述\n\n正常内容。\n\n## 改进建议\n\n不要的内容。\n\n## 核心流程\n\n保留内容。"
    result = _sanitize_published_content(content)
    assert "改进建议" not in result
    assert "核心流程" in result
    assert "保留内容" in result


def test_finalize_repairs_empty_code_blocks():
    content = "## 概述\n\n文本。\n\n```java\n```\n\n更多文本。"
    result = _sanitize_published_content(content)
    assert "```java" not in result
    assert "更多文本" in result


@pytest.mark.asyncio
async def test_finalize_uses_unified_hallucination_detection():
    """finalize_node should call content_guards hallucination detection."""
    long_body = "本模块负责用户认证与会话管理，采用 Redis 存储并通过 Token 验证保障安全。" * 80
    content = f"## 概述\n\n{long_body}"
    state = {
        "pages": [
            {
                "title": "Topic",
                "path": "/__domains__/test/unified-hallucination",
                "page_type": "topic",
                "content": content,
                "content_language": "zh",
                "metadata": {},
            }
        ]
    }
    mock_settings = MagicMock()
    mock_settings.wiki.topic_min_content_chars = 1000
    mock_settings.wiki.topic_min_publish_chars = 1500
    mock_settings.wiki.overview_min_content_chars = 2000
    mock_settings.wiki.cn_ratio_hard_min = 0.25

    with (
        patch("core.config.get_settings", return_value=mock_settings),
        patch(
            "wiki.nodes.finalize.detect_hallucination_flags",
            return_value=["fabricated_percentage"],
        ) as mock_detect,
    ):
        await finalize_node(state)

    mock_detect.assert_called()


def test_strip_agent_artifacts_removes_meta_sections():
    content = (
        "## 概述\n\n"
        "支付处理域负责核心支付逻辑。\n\n"
        "## 改进建议\n\n"
        "建议补充更多集成测试。\n\n"
        "## 关键实现\n\n"
        "PaymentService 的核心逻辑如下。"
    )
    result = strip_agent_artifacts(content)
    assert "改进建议" not in result
    assert "关键实现" in result
    assert "PaymentService" in result
