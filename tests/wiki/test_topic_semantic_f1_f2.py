"""Tests for F1 (semantic topic naming) and F2 (stub topic elimination)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.domain_doc_agent import _extract_chunk_title
from wiki.nodes.finalize import _rewrite_part_n_title, finalize_node
from wiki.nodes.quality_gate import quality_gate_node


def test_extract_chunk_title_single_module() -> None:
    modules = [{"name": "auth", "display_name": "Authentication Module"}]
    assert _extract_chunk_title(modules, "My Domain", 0) == "Authentication Module"


def test_extract_chunk_title_multiple_modules() -> None:
    modules = [
        {"name": "a", "display_name": "Short"},
        {"name": "b", "display_name": "Longer Module Name"},
        {"name": "c", "display_name": "Mid"},
    ]
    assert _extract_chunk_title(modules, "My Domain", 1) == "Longer Module Name"


def test_extract_chunk_title_fallback_part_n() -> None:
    modules = [
        {"name": "x", "display_name": "My Domain"},
        {"name": "y", "display_name": "My Domain"},
    ]
    assert _extract_chunk_title(modules, "My Domain", 2) == "My Domain - Section 3"


def test_rewrite_part_n_title_with_h2() -> None:
    title = "Payments - Part 2"
    content = "## 支付网关集成\n\n详细说明。"
    assert _rewrite_part_n_title(title, content) == "Payments - 支付网关集成"


def test_rewrite_part_n_title_skips_overview_h2() -> None:
    title = "Payments - Part 1"
    content = "## 概述\n\n仅概述。"
    assert _rewrite_part_n_title(title, content) == "Payments - Part 1"


def test_rewrite_part_n_title_no_change() -> None:
    title = "Payments - 支付网关"
    content = "## 概述\n\n内容。"
    assert _rewrite_part_n_title(title, content) == "Payments - 支付网关"


def _mock_quality_gate_eval() -> MagicMock:
    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    return mock_eval


def _mock_wiki_cfg(**overrides: object) -> MagicMock:
    wiki_cfg = MagicMock()
    wiki_cfg.heal_l2_threshold = 0.0
    wiki_cfg.heal_on_l3_failure = False
    wiki_cfg.heal_l3_threshold = 0.5
    wiki_cfg.overview_min_content_chars = 2000
    wiki_cfg.topic_min_content_chars = 500
    wiki_cfg.language_guardrail_cn_ratio = 0.15
    for key, value in overrides.items():
        setattr(wiki_cfg, key, value)
    return wiki_cfg


@pytest.mark.asyncio
async def test_quality_gate_detects_part_n_title() -> None:
    page = {
        "path": "/__domains__/pay/_topic/gateway",
        "title": "Payments - Part 2",
        "page_type": "topic",
        "content": "## 概述\n\n" + ("内容段落。" * 80),
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }
    mock_eval = _mock_quality_gate_eval()
    wiki_cfg = _mock_wiki_cfg()

    with (
        patch("wiki.nodes.quality_gate.get_settings", return_value=MagicMock(wiki=wiki_cfg)),
        patch("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval),
        patch(
            "wiki.nodes.quality_gate.verify_citations",
            lambda content, names: MagicMock(invalid_count=0),
        ),
    ):
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "part_n_title" in hint


@pytest.mark.asyncio
async def test_quality_gate_warns_short_topic() -> None:
    content = "## 概述\n\n简短占位内容。"
    assert len(content.strip()) < 500

    page = {
        "path": "/__domains__/pay/_topic/stub",
        "title": "Payments - Gateway",
        "page_type": "topic",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }
    mock_eval = _mock_quality_gate_eval()
    wiki_cfg = _mock_wiki_cfg()

    with (
        patch("wiki.nodes.quality_gate.get_settings", return_value=MagicMock(wiki=wiki_cfg)),
        patch("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval),
        patch(
            "wiki.nodes.quality_gate.verify_citations",
            lambda content, names: MagicMock(invalid_count=0),
        ),
    ):
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "content_too_short" in hint


@pytest.mark.asyncio
async def test_stub_topic_rejected_by_finalize() -> None:
    stub_banner = "> ⚠️ 本域文档待完善，内容可能不完整。\n\n"
    content = stub_banner  # well under 200 chars
    assert len(content.strip()) < 200

    page = {
        "title": "Stub Topic",
        "path": "/__domains__/test/_topic/stub",
        "page_type": "topic",
        "content": content,
        "content_language": "zh",
        "metadata": {},
    }
    state = {"pages": [page], "config": {"content_language": "zh"}, "errors": []}

    mock_settings = MagicMock()
    mock_settings.wiki.topic_min_content_chars = 100
    mock_settings.wiki.topic_min_publish_chars = 0
    mock_settings.wiki.overview_min_content_chars = 100
    mock_settings.wiki.cn_ratio_hard_min = 0.15

    with patch("core.config.get_settings", return_value=mock_settings):
        with patch("wiki.nodes.finalize.log") as mock_log:
            result = await finalize_node(state)

    rejected = next(p for p in result["pages"] if p["path"] == page["path"])
    assert rejected.get("__rejected__") is True
    assert rejected.get("content") == ""
    reject_calls = [
        c for c in mock_log.warning.call_args_list if c[0][0] == "page_too_short_rejected"
    ]
    assert len(reject_calls) == 1
