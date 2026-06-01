from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


_SKELETON_BANNER = "> ⚠️ 本域文档待完善，内容可能不完整。"


class TestSkeletonBannerInjection:
    @pytest.mark.asyncio
    async def test_skeleton_page_gets_banner(self):
        """Page < 2000 chars but > 500 chars (after banner) gets warning banner prepended."""
        from wiki.nodes.finalize import finalize_node

        filler = "该模块负责处理用户之间的社交关系操作与关系数据服务，是平台社交能力的核心支撑。" * 12
        short_content = f"## 概述\n\n{filler}\n\n## 核心业务流程\n\n{filler}"
        state = {
            "pages": [
                {
                    "title": "Test",
                    "path": "/__domains__/test/_overview",
                    "page_type": "domain_overview",
                    "content": short_content,
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert page["content"].startswith(_SKELETON_BANNER)

    @pytest.mark.asyncio
    async def test_normal_page_no_banner(self):
        """Page >= 2000 chars does NOT get banner."""
        from wiki.nodes.finalize import finalize_node

        long_content = "# Normal Domain\n\n## 概述\n\n" + ("这是一段中文内容。" * 230)
        state = {
            "pages": [
                {
                    "title": "Normal",
                    "path": "/__domains__/normal/_overview",
                    "page_type": "domain_overview",
                    "content": long_content,
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert not page["content"].startswith(_SKELETON_BANNER)

    @pytest.mark.asyncio
    async def test_short_topic_page_gets_banner(self):
        """Short topic pages get the same skeleton warning banner as domain_overview."""
        from wiki.nodes.finalize import finalize_node

        state = {
            "pages": [
                {
                    "title": "Topic",
                    "path": "/__domains__/test/topic-a",
                    "page_type": "topic",
                    "content": (
                        "# Short Topic\n\n"
                        + ("该模块负责处理用户之间的社交关系操作与关系数据服务，是平台社交能力的核心支撑。" * 5)
                    ),
                }
            ]
        }
        mock_settings = MagicMock()
        mock_settings.wiki.topic_min_content_chars = 1000
        mock_settings.wiki.topic_min_publish_chars = 0
        mock_settings.wiki.overview_min_content_chars = 2000
        mock_settings.wiki.cn_ratio_hard_min = 0.4
        with patch("core.config.get_settings", return_value=mock_settings):
            result = await finalize_node(state)
        page = result["pages"][0]
        assert page["content"].startswith(_SKELETON_BANNER)

    @pytest.mark.asyncio
    async def test_english_skeleton_gets_english_banner(self):
        """English domain_overview skeleton gets English banner (content > 500 chars after banner)."""
        from wiki.nodes.finalize import finalize_node

        filler = "The billing module handles all subscription and payment business logic for users including order creation and payment verification. " * 5
        state = {
            "pages": [
                {
                    "title": "Test",
                    "path": "/__domains__/test/_overview",
                    "page_type": "domain_overview",
                    "content_language": "en",
                    "content": f"## Overview\n\n{filler}\n\n## Dependencies\n\n{filler}",
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert "incomplete" in page["content"].lower()
        assert "⚠️" in page["content"]

    @pytest.mark.asyncio
    async def test_topic_index_overview_no_banner(self):
        """Short topic-index overview (from _write_with_outline) does NOT get banner."""
        from wiki.nodes.finalize import finalize_node

        state = {
            "pages": [
                {
                    "title": "Test Domain",
                    "path": "/__domains__/test/_overview",
                    "page_type": "domain_overview",
                    "content": "# Test Domain\n\n## Topic A\nDesc A\n\n## Topic B\nDesc B",
                    "metadata": {"overview_kind": "topic_index"},
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert not page["content"].startswith(_SKELETON_BANNER)
