from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestShellDomainReject:
    """Tests for F8: shell domain hard-reject threshold from config."""

    def test_overview_reject_threshold_matches_config(self):
        from wiki.nodes.finalize import _get_overview_reject_threshold

        mock_settings = MagicMock()
        mock_settings.wiki.overview_min_content_chars = 2000

        with patch("core.config.get_settings", return_value=mock_settings):
            assert _get_overview_reject_threshold() == 2000

    def test_short_content_below_threshold(self):
        from wiki.nodes.finalize import _get_overview_reject_threshold

        mock_settings = MagicMock()
        mock_settings.wiki.overview_min_content_chars = 2000

        content = "# intimacy-task\n\n## 子域概览\n\n短内容。"
        with patch("core.config.get_settings", return_value=mock_settings):
            assert len(content) < _get_overview_reject_threshold()

    def test_normal_content_above_threshold(self):
        from wiki.nodes.finalize import _get_overview_reject_threshold

        mock_settings = MagicMock()
        mock_settings.wiki.overview_min_content_chars = 2000

        content = "# Normal Domain\n\n## 概述\n\n" + "这是一段正常的域概述内容。" * 200
        with patch("core.config.get_settings", return_value=mock_settings):
            assert len(content) > _get_overview_reject_threshold()


class TestEarlyExitMinCharsDefault:
    def test_early_exit_min_chars_default_1500(self):
        from core.config import AppWikiFlags

        assert AppWikiFlags().domain_agent_early_exit_min_chars == 1500


class TestTopicSplitThreshold:
    """Tests for F7: topic split threshold change."""

    def test_default_threshold_is_4(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert flags.topic_force_split_threshold == 4
