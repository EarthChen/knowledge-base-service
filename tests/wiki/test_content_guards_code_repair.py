"""Tests for wiki.content_guards code block repair helpers (TDD)."""

from __future__ import annotations


class TestRepairUnclosedCodeBlocks:
    def test_single_unclosed_java_fence(self) -> None:
        from wiki.content_guards import detect_unclosed_code_blocks, repair_unclosed_code_blocks

        content = "## 概述\n\n```java\npublic class Foo {\n"
        assert detect_unclosed_code_blocks(content) is True
        result = repair_unclosed_code_blocks(content)
        assert result.rstrip().endswith("```")
        assert not detect_unclosed_code_blocks(result)

    def test_closed_block_unchanged(self) -> None:
        from wiki.content_guards import repair_unclosed_code_blocks

        content = "```java\npublic class Foo {}\n```"
        assert repair_unclosed_code_blocks(content) == content

    def test_multiple_lang_fences_without_closes(self) -> None:
        from wiki.content_guards import detect_unclosed_code_blocks, repair_unclosed_code_blocks

        content = "```java\nclass A {}\n```python\ndef b():\n    pass\n```kotlin\nfun c() {}"
        result = repair_unclosed_code_blocks(content)
        assert not detect_unclosed_code_blocks(result)
        assert result.rstrip().endswith("```")

    def test_multiple_unclosed_with_one_bare_close(self) -> None:
        from wiki.content_guards import detect_unclosed_code_blocks, repair_unclosed_code_blocks

        content = "```java\nclass A {}\n```\n```python\ndef b():\n    pass\n```kotlin\nfun c() {}"
        result = repair_unclosed_code_blocks(content)
        assert not detect_unclosed_code_blocks(result)
        trailing_fences = result.rstrip().count("```")
        assert trailing_fences >= 1

    def test_java_fence_with_language_tag_at_eof(self) -> None:
        from wiki.content_guards import repair_unclosed_code_blocks

        content = "## Example\n\n```java\npublic void run() {"
        result = repair_unclosed_code_blocks(content)
        assert result.endswith("\n```\n") or result.rstrip().endswith("```")

    def test_indented_fence_not_counted(self) -> None:
        from wiki.content_guards import repair_unclosed_code_blocks

        content = "## Notes\n\n    ```java\n    indented literal\n"
        assert repair_unclosed_code_blocks(content) == content

    def test_prose_inline_backticks_not_counted(self) -> None:
        from wiki.content_guards import repair_unclosed_code_blocks

        content = "## 概述\n\nUse ``` notation in prose.\n\n```python\nprint('ok')\n```\n"
        assert repair_unclosed_code_blocks(content) == content

    def test_fence_inside_codeblock_not_treated_as_close(self) -> None:
        from wiki.content_guards import repair_unclosed_code_blocks

        content = '```java\nString s = "```";\nSystem.out.println(s);\n'
        result = repair_unclosed_code_blocks(content)
        assert result.rstrip().endswith("```")
        assert 'String s = "```"' in result

    def test_empty_content_unchanged(self) -> None:
        from wiki.content_guards import repair_unclosed_code_blocks

        assert repair_unclosed_code_blocks("") == ""


class TestDetectUnclosedCodeBlocksEnhanced:
    def test_even_fence_count_still_unclosed(self) -> None:
        from wiki.content_guards import detect_unclosed_code_blocks

        content = "```java\na\n```\n```python\nb\n```kotlin\nc"
        assert detect_unclosed_code_blocks(content) is True

    def test_balanced_fences_returns_false(self) -> None:
        from wiki.content_guards import detect_unclosed_code_blocks

        content = "```java\na\n```\n\nText.\n\n```python\nb\n```"
        assert detect_unclosed_code_blocks(content) is False


class TestRepairTruncatedCodeBlocks:
    def test_closes_truncated_unclosed_block(self) -> None:
        from wiki.content_guards import detect_truncated_code_blocks, repair_truncated_code_blocks

        content = "Some text.\n\n```java\npublic class Foo {\n    // truncated"
        assert detect_truncated_code_blocks(content)
        result = repair_truncated_code_blocks(content)
        assert detect_truncated_code_blocks(result) == []
        assert result.rstrip().endswith("```")

    def test_closed_block_unchanged(self) -> None:
        from wiki.content_guards import repair_truncated_code_blocks

        content = "```python\ndef foo():\n    pass\n```"
        assert repair_truncated_code_blocks(content) == content

    def test_closes_last_of_multiple_blocks(self) -> None:
        from wiki.content_guards import detect_truncated_code_blocks, repair_truncated_code_blocks

        content = "```java\nclass A {}\n```\n\nMore text.\n\n```kotlin\nfun b() {"
        assert len(detect_truncated_code_blocks(content)) == 1
        result = repair_truncated_code_blocks(content)
        assert detect_truncated_code_blocks(result) == []

    def test_empty_content_unchanged(self) -> None:
        from wiki.content_guards import repair_truncated_code_blocks

        assert repair_truncated_code_blocks("") == ""
