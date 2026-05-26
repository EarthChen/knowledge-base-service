"""Tests for language consistency guardrail check."""
from __future__ import annotations

import pytest


class TestLanguageGuardrail:
    def test_all_chinese_headings_score_1(self):
        from wiki.domain_doc_agent import _check_language_consistency

        content = "# 标题\n## 概述\n内容\n## 核心业务流程\n流程\n## 模块详解\n详解"
        assert _check_language_consistency(content, "简体中文") == 1.0

    def test_all_english_headings_score_0(self):
        from wiki.domain_doc_agent import _check_language_consistency

        content = "# Title\n## Overview\nContent\n## Components\nStuff\n## Architecture\nArch"
        assert _check_language_consistency(content, "简体中文") == 0.0

    def test_mixed_headings_partial_score(self):
        from wiki.domain_doc_agent import _check_language_consistency

        content = "# 标题\n## Overview\n内容\n## 模块详解\nStuff"
        score = _check_language_consistency(content, "简体中文")
        assert 0.4 < score < 0.8  # 2 out of 3 headings are Chinese

    def test_no_headings_returns_1(self):
        from wiki.domain_doc_agent import _check_language_consistency

        content = "Just plain text without any headings."
        assert _check_language_consistency(content, "简体中文") == 1.0

    def test_english_target_scores_english_headings(self):
        from wiki.domain_doc_agent import _check_language_consistency

        content = "# Title\n## Overview\nContent"
        assert _check_language_consistency(content, "English") == 1.0


class TestLanguageConsistencyCheck:
    @pytest.mark.asyncio
    async def test_chinese_content_passes(self):
        """Content with high CN ratio should pass when target is Chinese."""
        from wiki.output_guardrail import LanguageConsistencyCheck

        check = LanguageConsistencyCheck()
        content = "# 家族系统概述\n\n这是一个关于家族系统的文档，包含了家族成员管理、家族任务、家族宝箱等核心功能。\n\n## 核心模块\n\n家族核心服务负责处理所有家族相关的业务逻辑。"
        result = await check.check(content, {"target_language": "简体中文", "cn_ratio_threshold": 0.4})
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_english_content_fails_for_chinese_target(self):
        """Content with low CN ratio should fail when target is Chinese."""
        from wiki.output_guardrail import LanguageConsistencyCheck

        check = LanguageConsistencyCheck()
        content = "# Family System Overview\n\nThis document covers the family system architecture including member management, task systems, and treasure chest functionality.\n\n## Core Components\n\nThe FamilyService handles all family-related business logic."
        result = await check.check(content, {"target_language": "简体中文", "cn_ratio_threshold": 0.4})
        assert result.passed is False
        assert any("cn_ratio" in issue.lower() or "ratio" in issue.lower() for issue in result.issues)

    @pytest.mark.asyncio
    async def test_english_target_skips_check(self):
        """When target language is English, CN ratio check should be skipped (auto-pass)."""
        from wiki.output_guardrail import LanguageConsistencyCheck

        check = LanguageConsistencyCheck()
        content = "This is English content with no Chinese characters."
        result = await check.check(content, {"target_language": "en"})
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_no_target_language_passes(self):
        """When no target_language is set in context, check should auto-pass."""
        from wiki.output_guardrail import LanguageConsistencyCheck

        check = LanguageConsistencyCheck()
        content = "Some content."
        result = await check.check(content, {})
        assert result.passed is True


class TestLanguageConsistencyCheckCodeStripping:
    @pytest.mark.asyncio
    async def test_code_blocks_excluded_from_ratio(self):
        """Code blocks should not count toward CN ratio calculation."""
        from wiki.output_guardrail import LanguageConsistencyCheck

        check = LanguageConsistencyCheck()
        content = (
            "# 业务概述\n\n"
            "这是一段中文描述，解释系统架构。\n\n"
            "```java\npublic class UserService {\n    public void getUser() {}\n}\n```\n\n"
            "以上代码展示了用户服务的核心接口。"
        )
        result = await check.check(content, {"target_language": "简体中文", "cn_ratio_threshold": 0.3})
        assert result.passed

    @pytest.mark.asyncio
    async def test_backtick_code_excluded(self):
        """Inline backtick code excluded from ratio."""
        from wiki.output_guardrail import LanguageConsistencyCheck

        check = LanguageConsistencyCheck()
        content = "这是关于 `UserService` 和 `OrderController` 的文档说明，使用了 `@Autowired` 注解。"
        result = await check.check(content, {"target_language": "简体中文", "cn_ratio_threshold": 0.3})
        assert result.passed
