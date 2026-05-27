"""Tests for F13 dangling wikilink removal in finalize."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.finalize import _remove_invalid_wikilinks, finalize_node


def _long_overview_content(*links: str) -> str:
    body = "本域负责家族数据管理与缓存策略，涵盖持久化、读写分离与失效处理等核心能力。" * 80
    link_lines = "\n".join(links)
    return f"# 家族系统\n\n{body}\n\n## 相关主题\n\n{link_lines}"


def _topic_page(title: str, path: str) -> dict:
    return {
        "title": title,
        "path": path,
        "page_type": "topic",
        "business_domain": "family-data",
        "content": f"## {title}\n\n" + ("主题详细说明。" * 250),
        "content_language": "zh",
        "metadata": {},
    }


def _overview_page(content: str) -> dict:
    return {
        "title": "家族数据",
        "path": "/__domains__/family-data/_overview",
        "page_type": "domain_overview",
        "business_domain": "family-data",
        "content": content,
        "content_language": "zh",
        "metadata": {"overview_kind": "topic_index"},
    }


def _mock_wiki_settings() -> MagicMock:
    mock_settings = MagicMock()
    mock_settings.wiki.topic_min_content_chars = 1000
    mock_settings.wiki.topic_min_publish_chars = 1500
    mock_settings.wiki.overview_min_content_chars = 2000
    mock_settings.wiki.cn_ratio_hard_min = 0.25
    return mock_settings


class TestRemoveInvalidWikilinksUnit:
    def test_dangling_wikilink_removed(self) -> None:
        content = "参见 [[家族数据持久化与缓存]] 了解详情。"
        valid = {"已存在的主题"}
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[家族数据持久化与缓存]]" not in result
        assert "家族数据持久化与缓存" in result

    def test_valid_wikilink_preserved(self) -> None:
        content = "参见 [[已存在的主题]] 了解详情。"
        valid = {"已存在的主题"}
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[已存在的主题]]" in result

    def test_multiple_dangling_wikilinks(self) -> None:
        content = "[[缺失主题A]]、[[缺失主题B]] 与 [[有效主题]]。"
        valid = {"有效主题"}
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[缺失主题A]]" not in result
        assert "[[缺失主题B]]" not in result
        assert "缺失主题A" in result
        assert "缺失主题B" in result
        assert "[[有效主题]]" in result


class TestDanglingWikilinkFinalizeIntegration:
    @pytest.mark.asyncio
    async def test_dangling_wikilink_removed_in_finalize(self) -> None:
        overview = _overview_page(
            _long_overview_content(
                "- [[家族数据持久化与缓存]]",
                "- [[已生成主题]]",
            )
        )
        topic = _topic_page("已生成主题", "/__domains__/family-data/topics/generated/_topic")
        state = {"pages": [overview, topic]}

        with patch("core.config.get_settings", return_value=_mock_wiki_settings()):
            result = await finalize_node(state)

        overview_content = next(p for p in result["pages"] if p["page_type"] == "domain_overview")["content"]
        assert "[[已生成主题]]" in overview_content
        assert "[[家族数据持久化与缓存]]" not in overview_content
        assert "家族数据持久化与缓存" in overview_content

    @pytest.mark.asyncio
    async def test_valid_wikilink_preserved_in_finalize(self) -> None:
        overview = _overview_page(_long_overview_content("- [[缓存读写策略]]"))
        topic = _topic_page("缓存读写策略", "/__domains__/family-data/topics/cache/_topic")
        state = {"pages": [overview, topic]}

        with patch("core.config.get_settings", return_value=_mock_wiki_settings()):
            result = await finalize_node(state)

        overview_content = next(p for p in result["pages"] if p["page_type"] == "domain_overview")["content"]
        assert "[[缓存读写策略]]" in overview_content

    @pytest.mark.asyncio
    async def test_multiple_dangling_wikilinks_in_finalize(self) -> None:
        overview = _overview_page(
            _long_overview_content(
                "- [[孤儿 Part 2]]",
                "- [[孤儿 Part 3]]",
                "- [[有效主题]]",
            )
        )
        topic = _topic_page("有效主题", "/__domains__/family-data/topics/valid/_topic")
        state = {"pages": [overview, topic]}

        with patch("core.config.get_settings", return_value=_mock_wiki_settings()):
            result = await finalize_node(state)

        overview_content = next(p for p in result["pages"] if p["page_type"] == "domain_overview")["content"]
        assert "[[孤儿 Part 2]]" not in overview_content
        assert "[[孤儿 Part 3]]" not in overview_content
        assert "孤儿 Part 2" in overview_content
        assert "孤儿 Part 3" in overview_content
        assert "[[有效主题]]" in overview_content
