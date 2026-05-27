"""Tests for wiki quality fix v7 (F1-F4): reject leak, render cleanup, H2 dedup, hallucination."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.models.base import PageType, WikiPage, WikiPageMetadata
from wiki.nodes.finalize import (
    _dedup_h2_sections,
    _detect_hallucination_patterns,
    _sanitize_render_issues,
    finalize_node,
)
from wiki.persistence import WikiPagePersistence


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


def _rejected_page(result: dict, path: str) -> dict | None:
    for p in result.get("pages", []):
        if p.get("path") == path:
            return p if p.get("__rejected__") else None
    return None


# --- F1: reject leak fix ---


class TestFinalizeRejectMarker:
    @pytest.mark.asyncio
    async def test_finalize_stub_reject_marker(self) -> None:
        content = "# Stub\n\n" + ("短内容。" * 100)  # ~500 chars
        state = {"pages": [_topic_page("/__domains__/test/stub", content)]}
        mock_settings = _mock_wiki_settings(topic_min_publish_chars=1500)

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        rejected = _rejected_page(result, "/__domains__/test/stub")
        assert rejected is not None
        assert rejected.get("content") == ""
        assert rejected.get("__rejected__") is True

    @pytest.mark.asyncio
    async def test_finalize_cn_reject_marker(self) -> None:
        english = "This module handles authentication and session management. " * 40
        content = f"## Overview\n\n{english}"
        state = {"pages": [_topic_page("/__domains__/test/low-cn", content)]}
        mock_settings = _mock_wiki_settings(topic_min_publish_chars=0, cn_ratio_hard_min=0.25)

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        rejected = _rejected_page(result, "/__domains__/test/low-cn")
        assert rejected is not None
        assert rejected.get("__rejected__") is True

    @pytest.mark.asyncio
    async def test_finalize_hallucination_topic_reject_marker(self) -> None:
        content = "## 概述\n\n留存率提升了+12.3%，任务完成率+21.7%。\n\n" + _long_chinese_body(80)
        state = {"pages": [_topic_page("/__domains__/test/hallucinated", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        rejected = _rejected_page(result, "/__domains__/test/hallucinated")
        assert rejected is not None
        assert rejected.get("__rejected__") is True


class TestPersistFiltersRejected:
    @pytest.mark.asyncio
    async def test_persist_filters_rejected(self) -> None:
        store = MagicMock()
        store.persist_wiki_pages = AsyncMock(return_value=1)
        persistence = WikiPagePersistence(store, MagicMock(), None, MagicMock(), MagicMock())

        good = WikiPage(
            path="/good.md",
            title="Good",
            page_type=PageType.TOPIC,
            content="有效内容",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(node_count=0, edge_count=0),
        )
        bad = WikiPage(
            path="/bad.md",
            title="Bad",
            page_type=PageType.TOPIC,
            content="",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(node_count=0, edge_count=0),
        )
        setattr(bad, "__rejected__", True)

        await persistence.persist_pages_to_graph("repo1", [good, bad], skip_embedding=True)

        store.persist_wiki_pages.assert_awaited_once()
        persisted = store.persist_wiki_pages.await_args.args[1]
        paths = {d["path"] for d in persisted}
        assert "/good.md" in paths
        assert "/bad.md" not in paths


# --- F2: render cleanup ---


class TestSanitizeRenderIssues:
    def test_sanitize_empty_code_block(self) -> None:
        for raw in (
            "Intro\n\n```java\n\n```\n\nTail",
            "Intro\n\n```\n\n```\n\nTail",
            "A\n\n```python\n  \n```\n\nB",
        ):
            result = _sanitize_render_issues(raw)
            assert "```" not in result
            assert "Intro" in result or "A" in result

    def test_sanitize_empty_wikilink(self) -> None:
        content = "See [[]] and [[ valid ]] here."
        result = _sanitize_render_issues(content)
        assert "[[]]" not in result

    def test_sanitize_injected_ref(self) -> None:
        content = "Text <!-- __INJECTED_CODE_REF__abc123 --> more"
        result = _sanitize_render_issues(content)
        assert "__INJECTED_CODE_REF__" not in result
        assert "Text" in result and "more" in result

    def test_sanitize_excess_newlines(self) -> None:
        content = "A\n\n\n\n\n\nB"
        result = _sanitize_render_issues(content)
        assert "\n\n\n\n" not in result


# --- F3: H2 dedup ---


class TestDedupH2Sections:
    def test_dedup_h2_basic(self) -> None:
        content = (
            "# Title\n\n"
            "## 相关主题\n\nFirst section content.\n\n"
            "## 其他\n\nMiddle.\n\n"
            "## 相关主题\n\nLast section wins.\n"
        )
        result = _dedup_h2_sections(content)
        assert result.count("## 相关主题") == 1
        assert "Last section wins." in result
        assert "First section content." not in result

    def test_dedup_h2_no_change(self) -> None:
        content = "## A\n\nOne.\n\n## B\n\nTwo.\n"
        assert _dedup_h2_sections(content) == content


# --- F4: hallucination rules + overview reject ---


class TestHallucinationRulesExtended:
    def test_hallucination_tech_roadmap(self) -> None:
        for snippet in ("GNN 模型", "联邦学习方案", "LSTM 网络", "Transformer 架构", "GDPR 合规"):
            flags = _detect_hallucination_patterns(f"路线图包含 {snippet}。\n\n" + _long_chinese_body(5))
            assert "fabricated_tech_roadmap" in flags, f"expected flag for {snippet}"

    def test_hallucination_fabricated_timeline(self) -> None:
        flags = _detect_hallucination_patterns("Phase 2 将在 3-6个月 内完成。\n\n" + _long_chinese_body(5))
        assert "fabricated_timeline" in flags

    def test_hallucination_meta_self_reference(self) -> None:
        flags = _detect_hallucination_patterns("中文字符占比低于阈值。\n\n" + _long_chinese_body(5))
        assert "meta_self_reference" in flags


class TestHallucinationOverviewReject:
    @pytest.mark.asyncio
    async def test_hallucination_overview_reject(self) -> None:
        content = (
            "## 概述\n\n"
            "GNN 与联邦学习路线图 Phase 2 在 3-6个月 内完成，中文字符占比需优化。\n\n"
            + _long_chinese_body(80)
        )
        state = {"pages": [_overview_page("/__domains__/test/_overview", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            with patch("wiki.nodes.finalize.log") as mock_log:
                result = await finalize_node(state)

        rejected = _rejected_page(result, "/__domains__/test/_overview")
        assert rejected is not None
        assert rejected.get("__rejected__") is True
        reject_calls = [
            c for c in mock_log.warning.call_args_list if c[0][0] == "hallucination_overview_rejected"
        ]
        assert len(reject_calls) == 1

    @pytest.mark.asyncio
    async def test_hallucination_overview_banner_only(self) -> None:
        content = "## 概述\n\n留存率提升了+12.3%。\n\n" + _long_chinese_body(80)
        state = {"pages": [_overview_page("/__domains__/test/_overview", content)]}
        mock_settings = _mock_wiki_settings()

        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)

        pages = result.get("pages", [])
        assert len(pages) == 1
        assert not pages[0].get("__rejected__")
        assert pages[0]["content"].startswith("> ⚠️")


# --- F13: English Overview block sanitization ---


class TestSanitizeEnglishOverview:
    def test_sanitize_english_overview_removed(self) -> None:
        from wiki.nodes.finalize import _sanitize_english_overview

        content = (
            "> **Overview**: This module handles family messaging and event-driven "
            "integration across multiple services in the platform.\n\n"
            "## 概述\n\n"
            "本模块负责家族消息与事件驱动集成。\n"
        )
        result = _sanitize_english_overview(content)
        assert "**Overview**" not in result
        assert "family messaging" not in result
        assert "## 概述" in result

    def test_sanitize_chinese_overview_preserved(self) -> None:
        from wiki.nodes.finalize import _sanitize_english_overview

        content = (
            "> **Overview**: 本模块负责家族消息与事件驱动集成，"
            "协调多个服务之间的消息传递与事件处理流程。\n\n"
            "## 概述\n\n"
            "详细说明见下文。\n"
        )
        result = _sanitize_english_overview(content)
        assert "**Overview**" in result
        assert "家族消息" in result
