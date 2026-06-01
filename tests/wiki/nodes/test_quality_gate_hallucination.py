"""Tests for quality_gate hard-reject hallucination flags and module_overview checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.quality_gate import quality_gate_node


def _wiki_cfg() -> MagicMock:
    wiki_cfg = MagicMock()
    wiki_cfg.heal_l2_threshold = 0.0
    wiki_cfg.heal_on_l3_failure = False
    wiki_cfg.heal_l3_threshold = 0.5
    wiki_cfg.overview_min_content_chars = 2000
    wiki_cfg.topic_min_content_chars = 500
    wiki_cfg.language_guardrail_cn_ratio = 0.15
    return wiki_cfg


def _gate_patches(mock_eval: MagicMock):
    return (
        patch("wiki.nodes.quality_gate.get_settings"),
        patch("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval),
        patch(
            "wiki.nodes.quality_gate.verify_citations",
            lambda content, names: MagicMock(invalid_count=0),
        ),
    )


def _state(page: dict) -> dict:
    return {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }


def _topic_page(*, path: str, content: str, content_language: str = "简体中文") -> dict:
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


def _passing_topic_content(*, body: str) -> str:
    return (
        "## 概述\n"
        f"{body}\n"
        "## 关键组件\n"
        "核心模块处理请求。\n"
        "```java\npublic class AuthService {}\n```\n"
        "## 关联关系\n"
        "- [[peer-module]]\n"
    )


def _module_overview_page(*, path: str, content: str, content_language: str = "简体中文") -> dict:
    return {
        "path": path,
        "title": "Test Module",
        "page_type": "module_overview",
        "content_language": content_language,
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }


def _module_overview_content(*, body: str, include_sparse_marker: bool = False) -> str:
    sparse = "\n_No nested graph children_\n" if include_sparse_marker else ""
    return f"## 模块概述\n{body}\n{sparse}## 核心职责\n模块职责说明段落。\n## 依赖关系\n- [[peer-module]]\n"


@pytest.mark.asyncio
async def test_hard_reject_flag_triggers_heal():
    """fabricated_latency_sla must route the page into pages_to_heal."""
    body = "该模块负责请求路由与负载均衡，服务 SLA 要求 P99 < 5ms 以满足低延迟场景。" * 30
    page = _topic_page(
        path="/wiki/hard-hallucination",
        content=_passing_topic_content(body=body),
    )

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)

    patches = _gate_patches(mock_eval)
    with patches[0] as mock_settings, patches[1], patches[2]:
        mock_settings.return_value = MagicMock(wiki=_wiki_cfg())
        result = await quality_gate_node(_state(page), {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "Remove fabricated SLA/performance metrics" in hint
    assert "hallucination_hard" in hint


@pytest.mark.asyncio
async def test_soft_flag_stays_as_warning():
    """narrative_date and other soft flags must not trigger heal when scores pass."""
    body = "该模块在 2024-01-15 完成重构，负责用户认证与授权流程。" * 40
    page = _topic_page(
        path="/wiki/soft-hallucination",
        content=_passing_topic_content(body=body),
    )

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)

    patches = _gate_patches(mock_eval)
    with patches[0] as mock_settings, patches[1], patches[2]:
        mock_settings.return_value = MagicMock(wiki=_wiki_cfg())
        result = await quality_gate_node(_state(page), {"configurable": {}})

    assert page["path"] not in result.get("pages_to_heal", [])
    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "hallucination" not in hint


@pytest.mark.asyncio
async def test_sparse_module_detected():
    """Empty graph marker with inflated length should heal module_overview pages."""
    body = "该模块负责缓存与数据访问层协调。" * 120
    content = _module_overview_content(body=body, include_sparse_marker=True)
    assert len(content) > 2000
    assert "_No nested graph children_" in content

    page = _module_overview_page(path="/wiki/sparse-module", content=content)

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)

    patches = _gate_patches(mock_eval)
    with patches[0] as mock_settings, patches[1], patches[2]:
        mock_settings.return_value = MagicMock(wiki=_wiki_cfg())
        result = await quality_gate_node(_state(page), {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "sparse_module_over_inflated" in hint


@pytest.mark.asyncio
async def test_module_low_cn_detected():
    """module_overview with cn_ratio below 0.35 should enter heal pipeline."""
    total = 2500
    cn_count = int(total * 0.30)
    en_count = total - cn_count
    body = ("中" * cn_count) + ("a" * en_count)
    content = _module_overview_content(body=body)
    page = _module_overview_page(path="/wiki/low-cn-module", content=content)

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)

    patches = _gate_patches(mock_eval)
    with patches[0] as mock_settings, patches[1], patches[2]:
        mock_settings.return_value = MagicMock(wiki=_wiki_cfg())
        result = await quality_gate_node(_state(page), {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "module_overview_low_cn" in hint


@pytest.mark.asyncio
async def test_module_cn_ok_not_flagged():
    """module_overview with cn_ratio at or above 0.35 should not heal for language."""
    total = 2500
    cn_count = int(total * 0.40)
    en_count = total - cn_count
    body = ("中" * cn_count) + ("a" * en_count)
    content = _module_overview_content(body=body)
    page = _module_overview_page(path="/wiki/good-cn-module", content=content)

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)

    patches = _gate_patches(mock_eval)
    with patches[0] as mock_settings, patches[1], patches[2]:
        mock_settings.return_value = MagicMock(wiki=_wiki_cfg())
        result = await quality_gate_node(_state(page), {"configurable": {}})

    hint = result.get("heal_hints", {}).get(page["path"], "")
    assert "module_overview_low_cn" not in hint
