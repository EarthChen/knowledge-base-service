"""Tests for V9 Batch B content guards (F5-F9)."""

from __future__ import annotations

import pytest

from wiki.content_guards import (
    dedup_code_fences,
    detect_truncated_code_blocks,
    has_meta_sections,
    strip_english_self_reflection,
    strip_h1_title,
    strip_meta_sections,
    strip_repeated_blockquotes,
)


class TestStripH1Title:
    def test_strip_h1_title(self):
        content = "# 家族系统\n## 概述\n内容"
        result = strip_h1_title(content)
        assert result == "## 概述\n内容"

    def test_strip_h1_title_preserves_code_block(self):
        content = "```python\n# comment\nprint('hi')\n```\n## 概述\n内容"
        result = strip_h1_title(content)
        assert "# comment" in result
        assert result == content

    def test_strip_h1_title_no_h1(self):
        content = "## 概述\n内容"
        result = strip_h1_title(content)
        assert result == content

    def test_strip_h1_title_empty(self):
        assert strip_h1_title("") == ""
        assert strip_h1_title(None) == ""  # type: ignore[arg-type]

    def test_strip_h1_title_leading_newlines(self):
        content = "\n\n# Title\ncontent"
        result = strip_h1_title(content)
        assert result == "content"

    def test_strip_h1_title_leading_spaces(self):
        content = "  # Title\ncontent"
        result = strip_h1_title(content)
        assert result == "content"

    def test_strip_h1_title_fence_in_middle_preserved(self):
        content = "## Intro\n\n```python\n# comment\n```"
        result = strip_h1_title(content)
        assert "# comment" in result
        assert result == content


class TestMetaSectionExpanded:
    @pytest.mark.parametrize(
        "heading",
        [
            "章节导航",
            "Section Navigation",
            "待完善项",
            "待完善与风险提示",
            "补充说明",
            "中文说明补充",
            "CONTEXT_GAP",
            "中英对照",
            "术语表",
            "术语表（中英对照）",
        ],
    )
    def test_meta_section_expanded(self, heading: str):
        content = f"## 概述\n\n正常内容。\n\n## {heading}\n\n应删除的内容。\n\n## 核心流程\n\n保留内容。"
        assert has_meta_sections(content) is True
        result = strip_meta_sections(content)
        assert heading not in result
        assert "应删除的内容" not in result
        assert "保留内容" in result


class TestStripRepeatedBlockquotes:
    def test_strip_repeated_blockquotes(self):
        quote = "> 术语说明：本模块负责用户管理。"
        content = f"{quote}\n{quote}\n{quote}\n\n## 概述\n内容"
        result = strip_repeated_blockquotes(content)
        assert result.count("> 术语说明：本模块负责用户管理。") == 1
        assert "## 概述" in result

    def test_strip_repeated_blockquotes_different(self):
        content = "> 第一段说明。\n> 第二段不同说明。\n\n## 概述\n内容"
        result = strip_repeated_blockquotes(content)
        assert "> 第一段说明。" in result
        assert "> 第二段不同说明。" in result

    def test_strip_llm_trace_blockquotes(self):
        content = "> 术语说明：为提升中文读者理解\n\n## 概述\n内容"
        result = strip_repeated_blockquotes(content)
        assert "术语说明：为提升中文读者理解" not in result
        assert "## 概述" in result


class TestDedupCodeFences:
    def test_dedup_code_fences(self):
        block = "```java\npublic class Foo {}\n```"
        content = f"## 概述\n\n{block}\n\n更多内容。\n\n{block}\n\n{block}"
        result = dedup_code_fences(content)
        assert result.count("public class Foo") == 1
        assert "更多内容" in result

    def test_dedup_code_fences_different(self):
        content = "## 概述\n\n```java\npublic class Foo {}\n```\n\n```java\npublic class Bar {}\n```"
        result = dedup_code_fences(content)
        assert "public class Foo" in result
        assert "public class Bar" in result

    def test_dedup_code_fences_empty(self):
        assert dedup_code_fences("") == ""
        assert dedup_code_fences(None) == ""  # type: ignore[arg-type]

    def test_dedup_code_fences_no_excessive_blank_lines(self):
        block = "```java\npublic class Foo {}\n```"
        content = f"## 概述\n\n{block}\n\n更多内容。\n\n{block}\n\n{block}"
        result = dedup_code_fences(content)
        assert "\n\n\n" not in result


class TestStripEnglishSelfReflection:
    def test_strip_english_self_reflection(self):
        content = "> **Note**: The headings in this document are placeholders.\n\n## Overview\n\nActual content."
        result = strip_english_self_reflection(content)
        assert "**Note**: The headings" not in result
        assert "## Overview" in result
        assert "Actual content" in result

    def test_strip_english_self_reflection_preserves_normal(self):
        content = "> This is a normal blockquote about the API design.\n\n## Overview\nContent."
        result = strip_english_self_reflection(content)
        assert "> This is a normal blockquote about the API design." in result

    def test_strip_english_self_reflection_the_following(self):
        content = "> The following section is a placeholder overview.\n\n## Overview\n\nActual content."
        result = strip_english_self_reflection(content)
        assert "placeholder overview" not in result
        assert "Actual content" in result


class TestDetectTruncatedCodeBlocks:
    def test_detect_truncated_marker(self):
        content = "## 示例\n\n```java\npublic class Foo {\n    // ...\n[truncated]\n```"
        assert detect_truncated_code_blocks(content) is True

    def test_detect_truncated_unclosed_fence(self):
        content = "## 示例\n\n```java\npublic class Foo {\n    return 1;\n"
        assert detect_truncated_code_blocks(content) is True

    def test_detect_truncated_incomplete_line(self):
        content = (
            "## 示例\n\n```java\n"
            "public void processOrder(Order order) {\n"
            "    validate(order);\n"
            "    repository.save(order,\n"
            "```"
        )
        assert detect_truncated_code_blocks(content) is True

    def test_detect_truncated_normal_code_no_false_positive(self):
        content = (
            "## 示例\n\n```java\n"
            "public void foo() {\n"
            "    doWork();\n"
            "}\n"
            "```"
        )
        assert detect_truncated_code_blocks(content) is False

    def test_detect_truncated_short_block_skipped(self):
        content = "## 示例\n\n```java\nx,\n```"
        assert detect_truncated_code_blocks(content) is False

    def test_detect_truncated_empty_content(self):
        assert detect_truncated_code_blocks("") is False
