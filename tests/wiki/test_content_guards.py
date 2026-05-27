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
