"""Tests for cn_ratio hard gate in heal post-check."""
from __future__ import annotations

from unittest.mock import MagicMock

from wiki.nodes.heal import _page_passes_post_heal


class TestPagePassesPostHealCnRatio:
    """Verify that _page_passes_post_heal rejects low CN ratio pages."""

    def _make_page(self, content: str, page_type: str = "topic", path: str = "/__domains__/test/_topic"):
        page = MagicMock()
        page.content = content
        page.path = path
        page.page_type = page_type
        page.metadata = {}
        return page

    def _make_state(self, content_language: str = "zh"):
        return {
            "config": {
                "importance_tiers": {},
                "content_language": content_language,
            }
        }

    def test_english_topic_rejected(self):
        """Topic with pure English content should fail post-heal check."""
        page = self._make_page(
            "## Overview\n\nThis module handles user authentication and session management.\n\n"
            "## Components\n\n- AuthService\n- SessionManager\n- TokenValidator\n\n"
            "## Relationships\n\nThe auth module depends on Redis for session storage." * 5
        )
        state = self._make_state("zh")
        evaluator = MagicMock()
        evaluator.structural_check.return_value = MagicMock(overall=0.8)

        result = _page_passes_post_heal(page, state, evaluator)
        assert result is False, "English-dominated topic should fail post-heal when language is Chinese"

    def test_chinese_topic_passes(self):
        """Topic with sufficient Chinese content should pass."""
        page = self._make_page(
            "## 概述\n\n本模块负责用户认证和会话管理。系统采用 Redis 存储会话数据，通过 Token 验证机制确保安全性。\n\n"
            "## 架构\n\n认证服务分为三层：接入层、验证层、存储层。" * 10
        )
        state = self._make_state("zh")
        evaluator = MagicMock()
        evaluator.structural_check.return_value = MagicMock(overall=0.8)

        result = _page_passes_post_heal(page, state, evaluator)
        assert result is True

    def test_english_content_passes_when_language_is_english(self):
        """English content should pass when target language is English."""
        page = self._make_page("## Overview\n\nThis handles authentication." * 10)
        state = self._make_state("en")
        evaluator = MagicMock()
        evaluator.structural_check.return_value = MagicMock(overall=0.8)

        result = _page_passes_post_heal(page, state, evaluator)
        assert result is True

    def test_overview_not_checked(self):
        """Overview pages should not be subject to cn_ratio hard gate."""
        page = self._make_page("## Overview\n\nEnglish content only." * 10, page_type="domain_overview")
        state = self._make_state("zh")
        evaluator = MagicMock()
        evaluator.structural_check.return_value = MagicMock(overall=0.8)

        result = _page_passes_post_heal(page, state, evaluator)
        assert result is True
