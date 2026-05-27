from __future__ import annotations


class TestShellDomainReject:
    """Tests for F8: shell domain hard-reject constant."""

    def test_shell_domain_min_chars_constant(self):
        from wiki.nodes.finalize import SHELL_DOMAIN_MIN_CHARS

        assert SHELL_DOMAIN_MIN_CHARS == 500

    def test_short_content_below_threshold(self):
        from wiki.nodes.finalize import SHELL_DOMAIN_MIN_CHARS

        content = "# intimacy-task\n\n## 子域概览\n\n短内容。"
        assert len(content) < SHELL_DOMAIN_MIN_CHARS

    def test_normal_content_above_threshold(self):
        from wiki.nodes.finalize import SHELL_DOMAIN_MIN_CHARS

        content = "# Normal Domain\n\n## 概述\n\n" + "这是一段正常的域概述内容。" * 100
        assert len(content) > SHELL_DOMAIN_MIN_CHARS


class TestTopicSplitThreshold:
    """Tests for F7: topic split threshold change."""

    def test_default_threshold_is_4(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert flags.topic_force_split_threshold == 4
