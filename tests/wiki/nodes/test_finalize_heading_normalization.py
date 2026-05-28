"""Tests for English → Chinese heading normalization in finalize."""
from __future__ import annotations

import pytest

from wiki.nodes.finalize import _normalize_headings_to_chinese, finalize_node


class TestNormalizeHeadingsToChinese:
    def test_replaces_common_h2_headings(self):
        content = "## Overview\n\nSome text\n\n## Key components"
        result = _normalize_headings_to_chinese(content)
        assert result == "## 概述\n\nSome text\n\n## 核心组件"

    def test_preserves_headings_inside_code_fence(self):
        content = "```\n## Overview\n```"
        result = _normalize_headings_to_chinese(content)
        assert result == "```\n## Overview\n```"

    def test_preserves_headings_inside_multiline_code_fence(self):
        content = "Intro\n\n```python\n## Overview\nprint(1)\n```\n\n## Architecture"
        result = _normalize_headings_to_chinese(content)
        assert "## Overview" in result
        assert "## 架构设计" in result

    def test_already_chinese_headings_unchanged(self):
        content = "## 概述\n\n## 核心组件"
        result = _normalize_headings_to_chinese(content)
        assert result == content

    def test_h3_headings_replaced(self):
        content = "### Overview\n\n### Key components"
        result = _normalize_headings_to_chinese(content)
        assert result == "### 概述\n\n### 核心组件"

    def test_empty_content_unchanged(self):
        assert _normalize_headings_to_chinese("") == ""
        assert _normalize_headings_to_chinese(None) is None  # type: ignore[arg-type]


class TestFinalizeHeadingNormalizationIntegration:
    @pytest.mark.asyncio
    async def test_chinese_page_headings_normalized_in_pipeline(self):
        para = "计费模块负责处理所有用户的订阅和支付相关业务逻辑" * 15
        content = f"## Overview\n\n{para}\n\n## Dependencies\n\n{para}"
        state = {
            "pages": [
                {
                    "path": "/__domains__/billing/overview",
                    "page_type": "domain_overview",
                    "title": "Billing",
                    "content": content,
                    "content_language": "zh",
                    "metadata": {},
                }
            ],
            "config": {"content_language": "zh"},
            "errors": [],
        }
        result = await finalize_node(state)
        out = result["pages"][0]["content"]
        assert "## 概述" in out
        assert "## 依赖关系" in out
        assert "## Overview" not in out
        assert "## Dependencies" not in out

    @pytest.mark.asyncio
    async def test_english_language_page_not_modified(self):
        body = "The billing module handles all subscription and payment business logic for users including order creation, payment verification, notification dispatch, and reconciliation. It uses an event-driven architecture with message queues for async decoupling to ensure system stability under high concurrency. Core components include the order service, payment gateway adapter, invoice generator and notification scheduler."
        content = f"## Overview\n\n{body}\n\n## Dependencies\n\n{body}"
        state = {
            "pages": [
                {
                    "path": "/__domains__/billing/overview",
                    "page_type": "domain_overview",
                    "title": "Billing",
                    "content": content,
                    "content_language": "en",
                    "metadata": {},
                }
            ],
            "config": {"content_language": "en"},
            "errors": [],
        }
        result = await finalize_node(state)
        out = result["pages"][0]["content"]
        assert "## Overview" in out
        assert "## 概述" not in out

    @pytest.mark.asyncio
    async def test_module_overview_gets_normalization(self):
        body = "该模块采用分层架构设计，包含控制器层、服务层和数据访问层。控制器负责请求路由和参数校验，服务层封装核心业务逻辑，数据访问层通过仓库模式抽象数据库操作。各层之间通过接口解耦，支持灵活替换实现。"
        content = f"## Overview\n\n{body}\n\n## Dependencies\n\n{body}"
        state = {
            "pages": [
                {
                    "path": "/__domains__/billing/module/foo",
                    "page_type": "module_overview",
                    "title": "Foo",
                    "content": content,
                    "content_language": "zh-cn",
                    "metadata": {},
                }
            ],
            "config": {},
            "errors": [],
        }
        result = await finalize_node(state)
        out = result["pages"][0]["content"]
        assert "## 概述" in out
        assert "## 依赖关系" in out
