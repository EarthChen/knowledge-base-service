"""Tests for hard-rejecting low CN-ratio topic pages in finalize."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.finalize import finalize_node


def _english_topic_content() -> str:
    return (
        "## Overview\n\nThis module handles authentication and session management for the platform."
    ) * 20


def _chinese_topic_content() -> str:
    return (
        "## 概述\n\n本模块负责用户认证管理，采用 Redis 存储会话并通过 Token 验证保障安全。"
        "系统分为接入层、验证层与存储层，支持多租户隔离与高可用部署。"
    ) * 30


def _topic_page(
    path: str,
    content: str,
    *,
    content_language: str = "zh",
) -> dict:
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


@pytest.fixture
def mock_wiki_settings() -> MagicMock:
    mock_settings = MagicMock()
    mock_settings.wiki.topic_min_content_chars = 100
    mock_settings.wiki.topic_min_publish_chars = 0
    mock_settings.wiki.overview_min_content_chars = 100
    mock_settings.wiki.cn_ratio_hard_min = 0.15
    return mock_settings


class TestFinalizeCnRatioReject:
    @pytest.mark.asyncio
    async def test_low_cn_ratio_chinese_topic_rejected(
        self, mock_wiki_settings: MagicMock
    ) -> None:
        state = {
            "pages": [_topic_page("/__domains__/test/low-cn", _english_topic_content())],
            "config": {"content_language": "zh"},
            "errors": [],
        }
        with patch("core.config.get_settings", return_value=mock_wiki_settings):
            with patch("wiki.nodes.finalize.log") as mock_log:
                result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/low-cn" not in paths
        reject_calls = [
            c for c in mock_log.warning.call_args_list if c[0][0] == "low_cn_ratio_topic_rejected"
        ]
        assert len(reject_calls) == 1

    @pytest.mark.asyncio
    async def test_good_cn_ratio_chinese_topic_published(
        self, mock_wiki_settings: MagicMock
    ) -> None:
        state = {
            "pages": [_topic_page("/__domains__/test/good-cn", _chinese_topic_content())],
            "config": {"content_language": "zh"},
            "errors": [],
        }
        with patch("core.config.get_settings", return_value=mock_wiki_settings):
            result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/good-cn" in paths

    @pytest.mark.asyncio
    async def test_low_cn_ratio_english_config_topic_published(
        self, mock_wiki_settings: MagicMock
    ) -> None:
        state = {
            "pages": [
                _topic_page(
                    "/__domains__/test/en-lang",
                    _english_topic_content(),
                    content_language="en",
                )
            ],
            "config": {"content_language": "en"},
            "errors": [],
        }
        with patch("core.config.get_settings", return_value=mock_wiki_settings):
            result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/en-lang" in paths

    @pytest.mark.asyncio
    async def test_low_cn_ratio_overview_not_rejected(
        self, mock_wiki_settings: MagicMock
    ) -> None:
        state = {
            "pages": [
                _overview_page("/__domains__/test/_overview", _english_topic_content())
            ],
            "config": {"content_language": "zh"},
            "errors": [],
        }
        with patch("core.config.get_settings", return_value=mock_wiki_settings):
            result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/_overview" in paths
