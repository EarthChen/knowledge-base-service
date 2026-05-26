"""Tests for enhanced finalize sanitization."""
from __future__ import annotations

import pytest

from wiki.nodes.finalize import _sanitize_published_content


class TestSanitizeEnhancements:
    def test_undefined_links_cleaned(self):
        """[undefined] text markers should be cleaned."""
        content = "See [undefined] for details. Also [undefined] here."
        result = _sanitize_published_content(content)
        assert "[undefined]" not in result

    def test_orphaned_code_ref_cleaned(self):
        """<!-- CODE_REF --> and <!-- UNVERIFIED_CODE --> comments should be removed."""
        content = "# Title\n\n<!-- CODE_REF: some.Class -->\nSome content.\n<!-- UNVERIFIED_CODE: other -->"
        result = _sanitize_published_content(content)
        assert "CODE_REF" not in result
        assert "UNVERIFIED_CODE" not in result

    def test_source_protocol_cleaned(self):
        """source:// protocol links should be removed."""
        content = "See source://repo/path/File.java for details."
        result = _sanitize_published_content(content)
        assert "source://" not in result

    def test_mermaid_unclosed_fixed(self):
        """Unclosed code blocks should be closed."""
        content = "# Title\n\n```mermaid\ngraph TD\n  A-->B\n\nMore text."
        result = _sanitize_published_content(content)
        assert result.count("```") % 2 == 0

    def test_excessive_blank_lines_collapsed(self):
        """4+ consecutive blank lines should collapse to max 3."""
        content = "# Title\n\n\n\n\n\nParagraph."
        result = _sanitize_published_content(content)
        assert "\n\n\n\n" not in result
