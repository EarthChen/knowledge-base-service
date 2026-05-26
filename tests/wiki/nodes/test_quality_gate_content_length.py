"""Tests for content length quality gate check."""
from __future__ import annotations

import pytest


class TestQualityGateContentLength:
    def test_short_overview_flagged_for_heal(self):
        """Overview page under min threshold should be flagged for healing."""
        from wiki.nodes.quality_gate import _check_min_content_length

        page = {"path": "/__domains__/test/_overview", "page_type": "domain_overview", "content": "# Test\n\nShort."}
        result = _check_min_content_length(page, overview_min=2000, topic_min=1000)
        assert result["below_threshold"] is True
        assert result["page_type"] == "domain_overview"

    def test_adequate_overview_passes(self):
        """Overview page above threshold should pass."""
        from wiki.nodes.quality_gate import _check_min_content_length

        content = "# Test Domain\n\n" + "这是一个详细的概述页面。" * 200
        page = {"path": "/__domains__/test/_overview", "page_type": "domain_overview", "content": content}
        result = _check_min_content_length(page, overview_min=2000, topic_min=1000)
        assert result["below_threshold"] is False

    def test_short_topic_flagged(self):
        """Topic page under min threshold should be flagged."""
        from wiki.nodes.quality_gate import _check_min_content_length

        page = {"path": "/__domains__/test/topic1", "page_type": "topic", "content": "# Topic\n\nBrief."}
        result = _check_min_content_length(page, overview_min=2000, topic_min=1000)
        assert result["below_threshold"] is True

    def test_no_content_field(self):
        """Page without content should be flagged."""
        from wiki.nodes.quality_gate import _check_min_content_length

        page = {"path": "/__domains__/test/_overview", "page_type": "domain_overview"}
        result = _check_min_content_length(page, overview_min=2000, topic_min=1000)
        assert result["below_threshold"] is True

    def test_overview_min_reads_from_config(self):
        """When overview_min is omitted, threshold comes from wiki settings."""
        from unittest.mock import patch

        from wiki.nodes.quality_gate import _check_min_content_length

        page = {"page_type": "domain_overview", "content": "x" * 2500}
        with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
            mock_settings.return_value.wiki.overview_min_content_chars = 3000
            result = _check_min_content_length(page)
        assert result["threshold"] == 3000
        assert result["below_threshold"] is True
