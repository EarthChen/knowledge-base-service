"""Tests that DomainDocAgent sets executive_summary metadata."""
from __future__ import annotations

import pytest
from wiki.domain_doc_agent import _extract_executive_summary


class TestExtractExecutiveSummary:
    def test_extracts_first_paragraph(self):
        content = "# Auth Domain\n\nThis domain handles user authentication and authorization.\n\n## Overview\n\nMore details here."
        result = _extract_executive_summary(content)
        assert "authentication" in result
        assert "authorization" in result

    def test_skips_headings(self):
        content = "# Title\n\n## Subtitle\n\nActual summary paragraph here."
        result = _extract_executive_summary(content)
        assert "Actual summary" in result

    def test_empty_content(self):
        result = _extract_executive_summary("")
        assert result == ""

    def test_truncates_long_summary(self):
        content = "# Title\n\n" + "A" * 500 + "\n\nMore."
        result = _extract_executive_summary(content)
        assert len(result) <= 300
