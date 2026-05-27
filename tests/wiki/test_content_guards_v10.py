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
