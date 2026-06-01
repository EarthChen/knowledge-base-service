"""Tests for wiki.content_guards — unified content quality detection rules."""
from __future__ import annotations

import pytest


class TestDetectHallucinationFlags:
    def test_clean_content_returns_empty(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "## 概述\n\n用户管理模块负责处理用户的注册、登录和资料维护。"
        assert detect_hallucination_flags(content) == []

    def test_fabricated_decimal_percentage(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "缓存命中率达到 99.7%，显著提升了查询性能。"
        flags = detect_hallucination_flags(content)
        assert "fabricated_percentage" in flags

    def test_fabricated_round_percentage(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "系统可用性达到 99%，满足生产需求。"
        flags = detect_hallucination_flags(content)
        assert "fabricated_round_percentage" in flags

    def test_fabricated_latency_sla(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "接口响应时间 P99 ≤500ms，SLA > 99.9%。"
        flags = detect_hallucination_flags(content)
        assert "fabricated_latency_sla" in flags

    def test_code_blocks_excluded(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "## 概述\n\n正常内容。\n\n```java\nif (ratio > 99.7%) { return; }\n```"
        flags = detect_hallucination_flags(content)
        assert flags == []

    def test_fabricated_trend(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "性能优化后延迟 ↓35.2%，吞吐量 ↑20%。"
        flags = detect_hallucination_flags(content)
        assert "fabricated_trend" in flags

    def test_fabricated_sla(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "SLA ≥ 99.95%，P99 < 200ms，RTO < 30 分钟。"
        flags = detect_hallucination_flags(content)
        assert "fabricated_sla" in flags

    def test_fabricated_availability(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "系统可用性 99.999%，达到五个九标准。"
        flags = detect_hallucination_flags(content)
        assert "fabricated_availability" in flags

    def test_multiple_flags(self):
        from wiki.content_guards import detect_hallucination_flags

        content = "可用性 99.99%，P99 ≤500ms，性能 ↑20%。"
        flags = detect_hallucination_flags(content)
        assert len(flags) >= 2


class TestCountBoilerplateHits:
    def test_clean_content(self):
        from wiki.content_guards import count_boilerplate_hits

        content = "用户管理模块负责用户资料的增删改查。"
        assert count_boilerplate_hits(content) == 0

    def test_single_hit(self):
        from wiki.content_guards import count_boilerplate_hits

        content = "该模块遵循高内聚低耦合的设计原则。"
        assert count_boilerplate_hits(content) >= 1

    def test_multiple_hits(self):
        from wiki.content_guards import count_boilerplate_hits

        content = "高内聚低耦合的分层架构设计，显著提升了系统的核心价值在于高可用。"
        assert count_boilerplate_hits(content) >= 3

    def test_boilerplate_ratio_zero(self):
        from wiki.content_guards import boilerplate_ratio

        content = "用户管理模块负责处理用户的注册和登录。" * 10
        assert boilerplate_ratio(content) == 0.0

    def test_boilerplate_ratio_nonzero(self):
        from wiki.content_guards import boilerplate_ratio

        content = "高内聚低耦合。" * 5
        assert boilerplate_ratio(content) > 0.0


class TestMetaSections:
    def test_no_meta_sections(self):
        from wiki.content_guards import has_meta_sections

        content = "## 概述\n\n正常内容。\n\n## 核心业务流程\n\n流程描述。"
        assert has_meta_sections(content) is False

    def test_detect_improvement_suggestions(self):
        from wiki.content_guards import has_meta_sections

        content = "## 概述\n\n内容。\n\n## 改进建议\n\n建议内容。"
        assert has_meta_sections(content) is True

    def test_detect_glossary(self):
        from wiki.content_guards import has_meta_sections

        content = "## 概述\n\n内容。\n\n## 中文术语表\n\n术语内容。"
        assert has_meta_sections(content) is True

    def test_strip_meta_sections(self):
        from wiki.content_guards import strip_meta_sections

        content = "## 概述\n\n正常内容。\n\n## 改进建议\n\n不要的内容。\n\n## 核心流程\n\n保留内容。"
        result = strip_meta_sections(content)
        assert "概述" in result
        assert "核心流程" in result
        assert "改进建议" not in result

    def test_strip_preserves_non_meta(self):
        from wiki.content_guards import strip_meta_sections

        content = "## 概述\n\n内容。\n\n## 核心业务\n\n业务内容。"
        result = strip_meta_sections(content)
        assert result.strip() == content.strip()

    def test_detect_optimization_direction(self):
        from wiki.content_guards import has_meta_sections

        content = "## 优化方向\n\n内容。"
        assert has_meta_sections(content) is True

    def test_detect_summary_and_outlook(self):
        from wiki.content_guards import has_meta_sections

        content = "## 总结与展望\n\n回顾。"
        assert has_meta_sections(content) is True


class TestComputeCnRatio:
    def test_pure_chinese(self):
        from wiki.content_guards import compute_cn_ratio

        content = "这是一段完全中文的内容用于测试中文字符比例计算功能"
        ratio = compute_cn_ratio(content)
        assert ratio > 0.8

    def test_pure_english(self):
        from wiki.content_guards import compute_cn_ratio

        content = "This is a purely English paragraph for testing."
        ratio = compute_cn_ratio(content)
        assert ratio < 0.05

    def test_mixed_content(self):
        from wiki.content_guards import compute_cn_ratio

        content = "用户管理 UserManager 负责 login() 和 register() 操作。"
        ratio = compute_cn_ratio(content)
        assert 0.2 < ratio < 0.8

    def test_code_blocks_excluded(self):
        from wiki.content_guards import compute_cn_ratio

        content = "中文内容。\n\n```java\npublic class UserService {}\n```\n\n更多中文。"
        ratio = compute_cn_ratio(content)
        assert ratio > 0.3

    def test_empty_content(self):
        from wiki.content_guards import compute_cn_ratio

        assert compute_cn_ratio("") == 0.0

    def test_short_content_returns_one(self):
        from wiki.content_guards import compute_cn_ratio

        assert compute_cn_ratio("短") == 1.0


class TestCodeBlockIntegrity:
    def test_count_empty_code_blocks(self):
        from wiki.content_guards import count_empty_code_blocks

        content = "文本。\n\n```java\n```\n\n更多文本。\n\n```python\n```"
        assert count_empty_code_blocks(content) == 2

    def test_no_empty_code_blocks(self):
        from wiki.content_guards import count_empty_code_blocks

        content = "文本。\n\n```java\npublic class Foo {}\n```"
        assert count_empty_code_blocks(content) == 0

    def test_repair_removes_empty_blocks(self):
        from wiki.content_guards import repair_code_fences

        content = "文本。\n\n```java\n```\n\n更多文本。"
        result = repair_code_fences(content)
        assert "```java" not in result
        assert "更多文本" in result

    def test_repair_removes_empty_wikilinks(self):
        from wiki.content_guards import repair_code_fences

        content = "参见 [[]] 获取更多信息。"
        result = repair_code_fences(content)
        assert "[[]]" not in result

    def test_repair_preserves_valid_blocks(self):
        from wiki.content_guards import repair_code_fences

        content = "```java\npublic class Foo {}\n```"
        result = repair_code_fences(content)
        assert "public class Foo" in result


class TestStripH2TrailingWhitespace:
    def test_strip_h2_trailing_whitespace(self):
        from wiki.content_guards import strip_h2_trailing_whitespace

        content = "## 概述  \n\n正文。\n## 架构设计  \n\n更多内容。"
        result = strip_h2_trailing_whitespace(content)
        assert "## 概述  " not in result
        assert "## 概述\n" in result
        assert "## 架构设计\n" in result

    def test_strip_h2_trailing_whitespace_no_change(self):
        from wiki.content_guards import strip_h2_trailing_whitespace

        content = "## 概述\n\n正文。\n## 架构设计\n\n更多内容。"
        assert strip_h2_trailing_whitespace(content) == content


class TestSanitizeContentH2Strip:
    def test_sanitize_content_strips_h2_trailing_whitespace(self):
        from wiki.content_guards import sanitize_content

        content = "## 概述  \n\n正文。"
        result = sanitize_content(content)
        assert "## 概述  " not in result
        assert "## 概述\n" in result


class TestUnclosedCodeBlocks:
    def test_detect_unclosed_code_blocks(self):
        from wiki.content_guards import detect_unclosed_code_blocks

        content = "## 概述\n\n```java\npublic class Foo {\n"
        assert detect_unclosed_code_blocks(content) is True

    def test_detect_closed_code_blocks_returns_false(self):
        from wiki.content_guards import detect_unclosed_code_blocks

        content = "## 概述\n\n```java\npublic class Foo {}\n```"
        assert detect_unclosed_code_blocks(content) is False

    def test_repair_unclosed_code_blocks(self):
        from wiki.content_guards import repair_unclosed_code_blocks

        content = "## 概述\n\n```java\npublic class Foo {\n"
        result = repair_unclosed_code_blocks(content)
        assert result.endswith("```\n")
        assert result.count("```") % 2 == 0

    def test_repair_closed_code_blocks_no_change(self):
        from wiki.content_guards import repair_unclosed_code_blocks

        content = "```java\npublic class Foo {}\n```"
        assert repair_unclosed_code_blocks(content) == content


class TestIsCompoundModuleTitle:
    def test_detects_pipe_separator(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("ultron/ultron-relation|FamilyChestService") is True

    def test_passes_normal_chinese_title(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("家族宝箱奖励核心逻辑") is False

    def test_passes_english_title(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("Family Chest Reward") is False

    def test_detects_slash_repo_prefix(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("ultron/ultron-basic-user|LongListStringTypeHandler") is True

    def test_simple_name_with_pipe_no_path(self):
        from wiki.content_guards import is_compound_module_title

        # Just a pipe without path prefix should NOT match
        assert is_compound_module_title("hello|world") is False

    def test_detects_repo_pipe_without_slash(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("ultron|FamilyChestService") is True

    def test_compound_detection_all_audit_patterns(self):
        from wiki.content_guards import is_compound_module_title

        titles = [
            "ultron/ultron-basic-user|AppStoreStarPopWindowMoaService",
            "ultron/ultron-relation|FamilyChestService",
            "ultron/ultron-relation|FamilyChestWebService",
            "ultron/ultron-relation|FamilySquareRedisDao",
            "ultron/ultron-relation|FamilyTaskRedisDao",
            "ultron/ultron-basic-user|QuickMessageRemoteService",
            "ultron/ultron-relation|RelationRankService",
            "ultron/ultron-relation|RelationRankWebMoaService",
            "ultron/ultron-basic-user|LongListStringTypeHandler",
            "ultron/ultron-basic-user|LongTimestampTypeHandler",
            "ultron/ultron-basic-user|BasicUserPrivilegeDomainRepoV2",
        ]
        for title in titles:
            assert is_compound_module_title(title), f"Failed to detect: {title}"


class TestRewriteCompoundTitle:
    def test_rewrite_compound_title_produces_readable(self):
        from wiki.nodes.finalize import _rewrite_compound_title

        page = {
            "title": "ultron/ultron-relation|FamilyChestService",
            "business_domain": "family-chest-reward",
            "path": "/__domains__/family-chest-reward/relation-family-chest-service/_topic",
        }
        content = "## 概述\n\n家族宝箱奖励服务..."
        result = _rewrite_compound_title(page["title"], page, content)
        assert "|" not in result
        assert "/" not in result or result.startswith("http")
        assert len(result) > 2


class TestDeriveSemanticTitle:
    def test_uses_summary_first_sentence(self):
        from wiki.content_guards import derive_semantic_title

        result = derive_semantic_title(
            modules=["FamilyChestService"],
            domain_display_name="家族宝箱奖励",
            summaries={"FamilyChestService": {"summary_text": "家族宝箱奖励核心逻辑。负责发放和校验宝箱奖励。"}},
            content=None,
        )
        assert result == "家族宝箱奖励核心逻辑"

    def test_falls_back_to_h2_extraction(self):
        from wiki.content_guards import derive_semantic_title

        content = "## 概述\n\n关系榜单计算与排名服务，提供全局排行和好友排行。\n\n## 架构"
        result = derive_semantic_title(
            modules=["RelationRankService"],
            domain_display_name="关系榜单",
            summaries={},
            content=content,
        )
        # Should extract first non-empty line after ## heading
        assert "关系榜单" in result or "排名" in result

    def test_falls_back_to_domain_plus_role(self):
        from wiki.content_guards import derive_semantic_title

        result = derive_semantic_title(
            modules=["FamilyChestWebService"],
            domain_display_name="家族宝箱奖励",
            summaries={},
            content=None,
        )
        assert "家族宝箱奖励" in result

    def test_strips_repo_pipe_from_module(self):
        from wiki.content_guards import derive_semantic_title

        result = derive_semantic_title(
            modules=["ultron/ultron-relation|FamilyChestService"],
            domain_display_name="家族宝箱奖励",
            summaries={"FamilyChestService": {"summary_text": "家族宝箱核心服务"}},
            content=None,
        )
        assert "|" not in result

    def test_empty_modules_returns_empty_domain(self):
        from wiki.content_guards import derive_semantic_title

        result = derive_semantic_title(
            modules=[],
            domain_display_name="测试域",
            summaries={},
            content=None,
        )
        assert "测试域" in result
