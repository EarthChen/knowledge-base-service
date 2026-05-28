"""Tests for finalize node sanitization and redaction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.finalize import (
    _detect_hallucination_patterns,
    _sanitize_published_content,
    finalize_node,
)


class TestSanitizeSensitiveRedaction:
    def test_internal_url_replaced(self):
        content = "Deploy at http://10.0.0.5:3000/health before release."
        result = _sanitize_published_content(content)
        assert "[INTERNAL_URL]" in result
        assert "10.0.0.5" not in result

    def test_credentials_redacted(self):
        content = "Configure password: supersecret and secret=mytoken here."
        result = _sanitize_published_content(content)
        assert "supersecret" not in result
        assert "mytoken" not in result
        assert "[REDACTED]" in result


@pytest.mark.asyncio
async def test_remove_invalid_wikilinks_case_insensitive() -> None:
    """Wikilink matching should be case-insensitive to match links.py behavior."""
    pages = [
        {
            "title": "Invoicing",
            "path": "/__domains__/billing/topics/Invoicing.md",
            "business_domain": "billing",
            "content": (
                "Content with [[invoicing]] link. "
                "The invoicing module handles billing workflows, payment capture, "
                "and reconciliation against ledger entries for enterprise customers. "
                "Operators use it to issue invoices, apply credits, and export audit trails."
            ),
        },
    ]
    state = {"pages": pages}
    result = await finalize_node(state)
    content = result["pages"][0]["content"]
    assert "[[invoicing]]" in content


@pytest.mark.asyncio
async def test_remove_invalid_wikilinks_composite_case_insensitive() -> None:
    pages = [
        {
            "title": "Invoicing",
            "path": "/__domains__/billing/topics/Invoicing.md",
            "business_domain": "billing",
            "content": (
                "See [[billing/invoicing]] details. "
                "Billing domains coordinate subscription lifecycle, dunning, "
                "and tax reporting across regions with auditable settlement trails. "
                "Finance teams rely on these pages for month-end close and compliance reviews."
            ),
        },
    ]
    state = {"pages": pages}
    result = await finalize_node(state)
    content = result["pages"][0]["content"]
    assert "[[billing/invoicing]]" in content


def _long_chinese_body(repeat: int = 80) -> str:
    return "本模块负责用户认证与会话管理，采用 Redis 存储并通过 Token 验证保障安全。" * repeat


def _topic_page(path: str, content: str, *, content_language: str = "zh") -> dict:
    return {
        "title": "Topic",
        "path": path,
        "page_type": "topic",
        "content": content,
        "content_language": content_language,
        "metadata": {},
    }


def _overview_page(path: str, content: str) -> dict:
    return {
        "title": "Overview",
        "path": path,
        "page_type": "domain_overview",
        "content": content,
        "content_language": "zh",
        "metadata": {},
    }


def _mock_wiki_settings(**overrides: object) -> MagicMock:
    mock_settings = MagicMock()
    mock_settings.wiki.topic_min_content_chars = 1000
    mock_settings.wiki.topic_min_publish_chars = 1500
    mock_settings.wiki.overview_min_content_chars = 2000
    mock_settings.wiki.cn_ratio_hard_min = 0.25
    for key, value in overrides.items():
        setattr(mock_settings.wiki, key, value)
    return mock_settings


class TestDetectHallucinationPatterns:
    def test_fabricated_percentage_outside_code_block_flagged(self) -> None:
        content = "留存率提升了+12.3%，任务完成率+21.7%。\n\n" + _long_chinese_body(5)
        flags = _detect_hallucination_patterns(content)
        assert flags

    def test_percentage_inside_code_block_not_flagged(self) -> None:
        content = (
            "正常叙述文本。\n\n"
            "```python\n"
            "metrics = {'retention': '+12.3%', 'completion': '+21.7%'}\n"
            "```\n\n" + _long_chinese_body(5)
        )
        flags = _detect_hallucination_patterns(content)
        assert not flags

    def test_fabricated_sla_patterns_flagged(self) -> None:
        for snippet in ("SLA≤3s", "P95<15ms", "RTO<30s"):
            content = f"性能指标要求 {snippet}。\n\n" + _long_chinese_body(5)
            flags = _detect_hallucination_patterns(content)
            assert flags, f"expected flag for {snippet}"

    def test_narrative_date_flagged(self) -> None:
        content = "系统于2024-08-12完成上线。\n\n" + _long_chinese_body(5)
        flags = _detect_hallucination_patterns(content)
        assert flags


class TestFinalizeHallucinationReject:
    @pytest.mark.asyncio
    async def test_hallucination_topic_dropped_with_banner(self) -> None:
        content = "## 概述\n\n留存率提升了+12.3%，任务完成率+21.7%。\n\n" + _long_chinese_body(80)
        state = {"pages": [_topic_page("/__domains__/test/hallucinated", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            with patch("wiki.nodes.finalize.log") as mock_log:
                result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/hallucinated" in paths
        rejected = next(p for p in result["pages"] if p["path"] == "/__domains__/test/hallucinated")
        assert rejected.get("__rejected__") is True
        assert rejected.get("content") == ""
        hallucination_calls = [c for c in mock_log.warning.call_args_list if c[0][0] == "hallucination_detected"]
        assert len(hallucination_calls) == 1

    @pytest.mark.asyncio
    async def test_hallucination_overview_gets_banner_but_published(self) -> None:
        content = "## 概述\n\nSLA≤3s/P95<15ms/RTO<30s。\n\n" + _long_chinese_body(80)
        state = {"pages": [_overview_page("/__domains__/test/_overview", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        pages = result.get("pages", [])
        assert len(pages) == 1
        assert pages[0]["content"].startswith("> ⚠️")


class TestFinalizeStubRejectThreshold:
    @pytest.mark.asyncio
    async def test_topic_1200_chars_rejected(self) -> None:
        content = "# Topic\n\n" + ("这是一段中文文档内容。" * 108)  # ~1200 chars
        assert 1150 <= len(content) <= 1250
        state = {"pages": [_topic_page("/__domains__/test/short-topic", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            with patch("wiki.nodes.finalize.log") as mock_log:
                result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/short-topic" in paths
        rejected = next(p for p in result["pages"] if p["path"] == "/__domains__/test/short-topic")
        assert rejected.get("__rejected__") is True
        assert rejected.get("content") == ""
        reject_calls = [c for c in mock_log.warning.call_args_list if c[0][0] == "stub_topic_rejected"]
        assert len(reject_calls) == 1

    @pytest.mark.asyncio
    async def test_topic_1600_chars_published(self) -> None:
        content = "# Topic\n\n" + ("这是一段中文文档内容。" * 145)  # ~1600 chars
        assert len(content) >= 1600
        state = {"pages": [_topic_page("/__domains__/test/long-topic", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/long-topic" in paths

    @pytest.mark.asyncio
    async def test_overview_1200_chars_not_rejected_by_topic_threshold(self) -> None:
        content = "# Overview\n\n" + ("概述内容段落。" * 170)  # ~1200 chars
        assert 1150 <= len(content) <= 1250
        state = {"pages": [_overview_page("/__domains__/test/_overview", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/_overview" in paths


class TestFinalizeCnRatioThreshold:
    @pytest.mark.asyncio
    async def test_cn_ratio_020_rejected(self) -> None:
        english = "This module handles authentication and session management. " * 30
        chinese = "认证模块简介。"
        content = f"## 概述\n\n{chinese}\n\n{english}"
        assert len(content) >= 1500
        state = {"pages": [_topic_page("/__domains__/test/low-cn", content)]}
        mock_settings = _mock_wiki_settings(cn_ratio_hard_min=0.25)

        with patch("core.config.get_settings", return_value=mock_settings):
            with patch("wiki.nodes.finalize.log") as mock_log:
                result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/low-cn" in paths
        rejected = next(p for p in result["pages"] if p["path"] == "/__domains__/test/low-cn")
        assert rejected.get("__rejected__") is True
        assert rejected.get("content") == ""
        reject_calls = [c for c in mock_log.warning.call_args_list if c[0][0] == "low_cn_ratio_topic_rejected"]
        assert len(reject_calls) == 1

    @pytest.mark.asyncio
    async def test_cn_ratio_030_published(self) -> None:
        content = _long_chinese_body(80)
        state = {"pages": [_topic_page("/__domains__/test/good-cn", content)]}
        mock_settings = _mock_wiki_settings(cn_ratio_hard_min=0.25)

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/good-cn" in paths

    @pytest.mark.asyncio
    async def test_english_topic_not_rejected_by_cn_ratio(self) -> None:
        english = "This module handles authentication and session management. " * 40
        content = f"## Overview\n\n{english}"
        state = {
            "pages": [
                _topic_page(
                    "/__domains__/test/en-topic",
                    content,
                    content_language="en",
                )
            ]
        }
        mock_settings = _mock_wiki_settings(cn_ratio_hard_min=0.25)

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/en-topic" in paths
