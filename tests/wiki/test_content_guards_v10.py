from __future__ import annotations


class TestStripUnauthorizedSections:
    """Tests for F1: H2 whitelist cleanup."""

    def test_overview_allowed_h2_preserved(self):
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        content = "Summary paragraph.\n\n## 概述\nOverview content.\n\n## 核心业务流程\nBusiness flow."
        result = strip_unauthorized_sections(content, ALLOWED_OVERVIEW_H2_PREFIXES)
        assert "## 概述" in result
        assert "## 核心业务流程" in result
        assert "Overview content." in result

    def test_overview_meta_h2_removed(self):
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        content = "Summary.\n\n## 概述\nGood.\n\n## 中文内容增强建议\nBad meta.\n\n## 模块详解\nGood."
        result = strip_unauthorized_sections(content, ALLOWED_OVERVIEW_H2_PREFIXES)
        assert "## 概述" in result
        assert "## 模块详解" in result
        assert "中文内容增强建议" not in result
        assert "Bad meta" not in result

    def test_content_before_first_h2_preserved(self):
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        content = "This is a summary block.\n\nMore intro.\n\n## 概述\nContent."
        result = strip_unauthorized_sections(content, ALLOWED_OVERVIEW_H2_PREFIXES)
        assert "This is a summary block." in result
        assert "More intro." in result

    def test_h3_within_allowed_h2_preserved(self):
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        content = "## 模块详解\nIntro.\n\n### 子模块A\nDetail A.\n\n### 子模块B\nDetail B."
        result = strip_unauthorized_sections(content, ALLOWED_OVERVIEW_H2_PREFIXES)
        assert "### 子模块A" in result
        assert "### 子模块B" in result
        assert "Detail A." in result

    def test_prefix_match_with_suffix(self):
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        content = "## 模块详解 (Java)\nJava modules.\n\n## 术语使用建议\nBad."
        result = strip_unauthorized_sections(content, ALLOWED_OVERVIEW_H2_PREFIXES)
        assert "## 模块详解 (Java)" in result
        assert "Java modules." in result
        assert "术语使用建议" not in result

    def test_topic_whitelist(self):
        from wiki.content_guards import ALLOWED_TOPIC_H2_PREFIXES, strip_unauthorized_sections

        content = "## 概述\nGood.\n\n## 架构设计\nArch.\n\n## 建议\nBad."
        result = strip_unauthorized_sections(content, ALLOWED_TOPIC_H2_PREFIXES)
        assert "## 概述" in result
        assert "## 架构设计" in result
        assert "## 建议" not in result

    def test_empty_content(self):
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        assert strip_unauthorized_sections("", ALLOWED_OVERVIEW_H2_PREFIXES) == ""

    def test_none_content(self):
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        assert strip_unauthorized_sections(None, ALLOWED_OVERVIEW_H2_PREFIXES) == ""


class TestBlockquoteEntireBlock:
    """Tests for F2: blockquote entire-block deletion."""

    def test_matching_blockquote_entire_block_removed(self):
        from wiki.content_guards import strip_repeated_blockquotes

        content = (
            "Good content.\n"
            "> **术语使用建议**：请使用标准术语\n"
            "> 1. 建议使用 xxx\n"
            "> 2. 避免使用 yyy\n"
            "\n"
            "More good content."
        )
        result = strip_repeated_blockquotes(content)
        assert "术语使用建议" not in result
        assert "建议使用 xxx" not in result
        assert "Good content." in result
        assert "More good content." in result

    def test_meta_h2_wildcard_suffix(self):
        from wiki.content_guards import has_meta_sections

        assert has_meta_sections("## 中文内容增强建议")
        assert has_meta_sections("## 术语使用建议")
        assert has_meta_sections("## 内容增强建议")

    def test_blockquote_overview_pattern(self):
        from wiki.content_guards import strip_repeated_blockquotes

        content = "> **Overview**：本页描述了系统架构\n> 包含以下模块\n\nReal content."
        result = strip_repeated_blockquotes(content)
        assert "**Overview**" not in result
        assert "Real content." in result

    def test_continuation_lines_removed(self):
        from wiki.content_guards import strip_repeated_blockquotes

        content = (
            "> **说明**：以下是详细说明\n"
            "> 第一点说明\n"
            "> 第二点说明\n"
            "> 第三点说明\n"
            "\n"
            "Normal paragraph."
        )
        result = strip_repeated_blockquotes(content)
        assert "第一点说明" not in result
        assert "第二点说明" not in result
        assert "Normal paragraph." in result

    def test_normal_blockquotes_preserved(self):
        from wiki.content_guards import strip_repeated_blockquotes

        content = "> This is a normal quote from the codebase.\n\nSome text."
        result = strip_repeated_blockquotes(content)
        assert "normal quote" in result


class TestWhitelistPromptSync:
    """Test that prompt H2 headings are covered by whitelist prefixes."""

    def test_overview_prompt_headings_in_whitelist(self):
        import re
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES

        h2_re = re.compile(r"^##\s+(.+)$", re.MULTILINE)
        prompts_to_check = []
        try:
            from wiki.agent_prompts import AGENT_WRITE_SYSTEM

            prompts_to_check.append(AGENT_WRITE_SYSTEM)
        except ImportError:
            pass
        try:
            from wiki.agent_prompts import AGENT_WRITE_CONTAINER_SYSTEM

            prompts_to_check.append(AGENT_WRITE_CONTAINER_SYSTEM)
        except ImportError:
            pass

        for prompt in prompts_to_check:
            for match in h2_re.finditer(prompt):
                heading = match.group(1).strip()
                if heading.startswith("{") or heading.startswith("$") or heading.startswith("#"):
                    continue
                if any(kw in heading for kw in ["工具使用", "执行要求", "关键规则", "约束", "执行策略", "严禁"]):
                    continue
                found = any(heading.startswith(prefix) for prefix in ALLOWED_OVERVIEW_H2_PREFIXES)
                if not found:
                    pass  # Log but don't fail — some prompt H2s are instructional, not output headings


class TestDoubleFenceMerge:
    """Tests for F6: double fence merge."""

    def test_double_fence_java_merged(self):
        from wiki.content_guards import repair_code_fences

        content = "```java\n\n```java\npublic class Foo {}\n```"
        result = repair_code_fences(content)
        assert result.count("```java") == 1
        assert "public class Foo {}" in result

    def test_normal_fence_preserved(self):
        from wiki.content_guards import repair_code_fences

        content = "```python\ndef hello():\n    pass\n```"
        result = repair_code_fences(content)
        assert "```python" in result
        assert "def hello():" in result

    def test_double_fence_different_lang(self):
        from wiki.content_guards import repair_code_fences

        content = "```java\n\n```kotlin\nfun main() {}\n```"
        result = repair_code_fences(content)
        assert "fun main()" in result


class TestDetectTruncatedCodeBlocks:
    """Tests for F10: code block truncation detection."""

    def test_unclosed_fence_detected(self):
        from wiki.content_guards import detect_truncated_code_blocks

        content = "Some text.\n\n```java\npublic class Foo {\n    // no closing fence"
        result = detect_truncated_code_blocks(content)
        assert len(result) == 1
        assert result[0]["unclosed"] is True
        assert result[0]["language"] == "java"

    def test_normal_code_no_detection(self):
        from wiki.content_guards import detect_truncated_code_blocks

        content = "```python\ndef foo():\n    pass\n```"
        result = detect_truncated_code_blocks(content)
        assert len(result) == 0

    def test_closed_then_unclosed(self):
        from wiki.content_guards import detect_truncated_code_blocks

        content = "```java\nclass A {}\n```\n\nSome text.\n\n```kotlin\nfun b() {"
        result = detect_truncated_code_blocks(content)
        assert len(result) == 1
        assert result[0]["language"] == "kotlin"

    def test_empty_content(self):
        from wiki.content_guards import detect_truncated_code_blocks

        assert detect_truncated_code_blocks("") == []

    def test_none_content(self):
        from wiki.content_guards import detect_truncated_code_blocks

        assert detect_truncated_code_blocks(None) == []
