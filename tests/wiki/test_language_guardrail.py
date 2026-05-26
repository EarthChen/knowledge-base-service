from __future__ import annotations


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
