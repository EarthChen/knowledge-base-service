"""Tests for cn_ratio hard gate in finalize node."""
from __future__ import annotations

import pytest

from wiki.nodes.finalize import finalize_node


class TestFinalizeCnRatioGate:
    """Verify that finalize adds skeleton banner for low CN ratio topics."""

    @pytest.mark.asyncio
    async def test_english_topic_low_cn_ratio_rejected(self):
        """Topic with very low CN ratio under Chinese config is not published."""
        english_content = (
            "## Overview\n\nThis module handles authentication and session management for the platform."
        ) * 20
        state = {
            "pages": [
                {
                    "path": "/__domains__/test/topic1/_topic",
                    "page_type": "topic",
                    "title": "Test Topic",
                    "content": english_content,
                    "content_language": "zh",
                    "metadata": {},
                }
            ],
            "config": {"content_language": "zh"},
            "errors": [],
        }
        result = await finalize_node(state)
        pages = result.get("pages", [])
        assert not any(p.get("path") == "/__domains__/test/topic1/_topic" for p in pages)

    @pytest.mark.asyncio
    async def test_chinese_topic_no_banner(self):
        """Topic with good CN ratio should NOT get skeleton banner."""
        chinese_content = (
            "## 概述\n\n本模块负责用户认证管理，采用 Redis 存储会话并通过 Token 验证保障安全。"
            "系统分为接入层、验证层与存储层，支持多租户隔离与高可用部署。"
        ) * 30
        state = {
            "pages": [
                {
                    "path": "/__domains__/test/topic1/_topic",
                    "page_type": "topic",
                    "title": "测试主题",
                    "content": chinese_content,
                    "content_language": "zh",
                    "metadata": {},
                }
            ],
            "config": {"content_language": "zh"},
            "errors": [],
        }
        result = await finalize_node(state)
        pages = result.get("pages", state["pages"])
        assert "⚠️" not in pages[0]["content"]
