from __future__ import annotations

from wiki.nodes.finalize import _sanitize_published_content


def test_context_gap_removed():
    content = "# Title\n\nSome text.\n<!-- CONTEXT_GAP: missing info about X -->\nMore text."
    result = _sanitize_published_content(content)
    assert "CONTEXT_GAP" not in result
    assert "Some text." in result
    assert "More text." in result


def test_duplicate_headings_deduped():
    content = "## 依赖关系\n## 依赖关系\nContent A\nContent B"
    result = _sanitize_published_content(content)
    assert result.count("## 依赖关系") == 1
    assert "Content A" in result
    assert "Content B" in result


def test_unclosed_code_block_closed():
    content = "# Title\n```mermaid\ngraph TD\n    A --> B"
    result = _sanitize_published_content(content)
    assert result.count("```") % 2 == 0
    assert result.endswith("```")


def test_normal_content_unchanged():
    content = "## Clean page\n\nNo gaps here.\n\n```python\nprint('ok')\n```"
    result = _sanitize_published_content(content)
    assert result == content


def test_excessive_blank_lines_trimmed():
    content = "Line one\n\n\n\n\nLine two"
    result = _sanitize_published_content(content)
    assert "\n\n\n\n" not in result
    assert "Line one" in result
    assert "Line two" in result


class TestQualityChecklistRemoval:
    def test_removes_emoji_table(self):
        content = (
            "# Title\n\n"
            "Some text.\n\n"
            "| Check | Status |\n"
            "|-------|--------|\n"
            "| Coverage | ✅ |\n"
            "| Format | ⚠️ |\n\n"
            "More text."
        )
        result = _sanitize_published_content(content)
        assert "✅" not in result
        assert "⚠️" not in result
        assert "More text." in result
        assert "Some text." in result

    def test_keeps_normal_table(self):
        content = (
            "# Title\n\n"
            "| Name | Type |\n"
            "|------|------|\n"
            "| foo | string |\n"
        )
        result = _sanitize_published_content(content)
        assert "foo" in result
        assert "string" in result


class TestFakeSourcePathRemoval:
    def test_removes_com_xxx_line(self):
        content = "# Title\n\nSee `com/xxx/service/UserService.java` for details.\n\nReal content."
        result = _sanitize_published_content(content)
        assert "com/xxx/" not in result
        assert "Real content." in result

    def test_removes_com_xxx_code_block(self):
        content = "# Title\n\n```java\n// com/xxx/service/UserService.java\npublic class UserService {}\n```\n\nAfter."
        result = _sanitize_published_content(content)
        assert "com/xxx/" not in result
        assert "After." in result


class TestThinkingTagRemoval:
    def test_removes_think_tags(self):
        content = "# Title\n\n<think>internal reasoning here</think>\n\nVisible content."
        result = _sanitize_published_content(content)
        assert "<think>" not in result
        assert "</think>" not in result
        assert "Visible content." in result

    def test_removes_multiline_think(self):
        content = "# Title\n\n<think>\nline1\nline2\n</think>\n\nAfter."
        result = _sanitize_published_content(content)
        assert "<think>" not in result
        assert "After." in result


class TestContextGapEnhanced:
    def test_removes_context_gap_text_marker(self):
        content = "# Title\n\n[CONTEXT_GAP: missing info]\n\nReal text."
        result = _sanitize_published_content(content)
        assert "CONTEXT_GAP" not in result
        assert "Real text." in result

    def test_removes_context_gap_html_comment(self):
        content = "# Title\n\n<!-- CONTEXT_GAP: gap -->\n\nBody."
        result = _sanitize_published_content(content)
        assert "CONTEXT_GAP" not in result
        assert "Body." in result


class TestSourceProtocolRemoval:
    def test_removes_source_protocol_inline(self):
        content = "# Title\n\nSee source://ultron/FamilyPowerService for details.\n\nReal content."
        result = _sanitize_published_content(content)
        assert "source://" not in result
        assert "Real content." in result

    def test_removes_source_protocol_in_link(self):
        content = "# Title\n\n[FamilyService](source://ultron/FamilyService)\n\nAfter."
        result = _sanitize_published_content(content)
        assert "source://" not in result
        assert "After." in result

    def test_keeps_http_links(self):
        content = "# Title\n\nSee [docs](https://example.com) for info."
        result = _sanitize_published_content(content)
        assert "https://example.com" in result


class TestCodeRefCommentRemoval:
    def test_removes_code_ref_comment(self):
        content = "# Title\n\n<!-- CODE_REF: FamilyService.java -->\n\nVisible content."
        result = _sanitize_published_content(content)
        assert "CODE_REF" not in result
        assert "Visible content." in result

    def test_removes_unverified_code_comment(self):
        content = "# Title\n\n<!-- UNVERIFIED_CODE: some.Class -->\n\nAfter."
        result = _sanitize_published_content(content)
        assert "UNVERIFIED_CODE" not in result
        assert "After." in result

    def test_removes_multiline_code_ref(self):
        content = "# Title\n\n<!-- CODE_REF:\n  file1.java\n  file2.java\n-->\n\nBody."
        result = _sanitize_published_content(content)
        assert "CODE_REF" not in result
        assert "Body." in result

    def test_keeps_normal_html_comments(self):
        content = "# Title\n\n<!-- Regular comment -->\n\nBody."
        result = _sanitize_published_content(content)
        assert "<!-- Regular comment -->" in result


class TestWikilinkSlugTitle:
    def test_slug_title_format_valid(self):
        from wiki.nodes.finalize import _remove_invalid_wikilinks

        valid = {"domain-01/Core Modules", "PageA"}
        content = "See [[domain-01/Core Modules]] and [[PageA]]."
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[domain-01/Core Modules]]" in result
        assert "[[PageA]]" in result

    def test_removes_invalid_slug_title(self):
        from wiki.nodes.finalize import _remove_invalid_wikilinks

        valid = {"PageA"}
        content = "See [[nonexistent/page]]."
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[" not in result
        assert "nonexistent/page" in result
