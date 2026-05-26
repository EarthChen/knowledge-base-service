from __future__ import annotations

import pytest


_SKELETON_BANNER = "> ⚠️ 本域文档待完善，内容可能不完整。"


class TestSkeletonBannerInjection:
    @pytest.mark.asyncio
    async def test_skeleton_page_gets_banner(self):
        """Page < 2000 chars of type domain_overview gets warning banner prepended."""
        from wiki.nodes.finalize import finalize_node

        short_content = "# Test Domain\n\n## 概述\n\nShort.\n\n## 核心业务流程\n\n## 依赖关系\n"
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
    async def test_topic_page_no_banner(self):
        """Short topic pages do NOT get banner (only domain_overview)."""
        from wiki.nodes.finalize import finalize_node

        state = {
            "pages": [
                {
                    "title": "Topic",
                    "path": "/__domains__/test/topic-a",
                    "page_type": "topic",
                    "content": "# Short Topic\n\nBrief.",
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert not page["content"].startswith(_SKELETON_BANNER)

    @pytest.mark.asyncio
    async def test_english_skeleton_gets_english_banner(self):
        """English domain_overview skeleton gets English banner."""
        from wiki.nodes.finalize import finalize_node

        state = {
            "pages": [
                {
                    "title": "Test",
                    "path": "/__domains__/test/_overview",
                    "page_type": "domain_overview",
                    "content_language": "en",
                    "content": "# Test Domain\n\nShort.",
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
