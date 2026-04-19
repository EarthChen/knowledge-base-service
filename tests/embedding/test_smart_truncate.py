"""Tests for the _smart_truncate function in embedding_generator."""

import pytest

from indexer.embedding_generator import MAX_CODE_SNIPPET_CHARS, _smart_truncate


class TestSmartTruncate:
    """Unit tests for _smart_truncate."""

    def test_short_code_no_truncation(self):
        """Code shorter than max_chars should be returned as-is."""
        code = "def foo():\n    return 42\n"
        assert _smart_truncate(code) == code

    def test_exact_limit_no_truncation(self):
        """Code exactly at max_chars should not be truncated."""
        code = "x" * MAX_CODE_SNIPPET_CHARS
        assert _smart_truncate(code) == code

    def test_long_code_truncates_at_blank_line(self):
        """Long code should prefer blank line as break point."""
        lines = ["def foo():"] + [f"    line_{i} = {i}" for i in range(500)]
        # Insert a blank line near the end of the 3000-char window
        code = "\n".join(lines)
        if len(code) > MAX_CODE_SNIPPET_CHARS:
            # Insert blank line within the search window
            insert_pos = MAX_CODE_SNIPPET_CHARS - 100
            code = code[:insert_pos] + "\n\n" + code[insert_pos:]
            result = _smart_truncate(code)
            assert len(result) <= MAX_CODE_SNIPPET_CHARS
            assert result.endswith("\n\n") or result.rstrip().endswith("\n")

    def test_long_code_truncates_at_semicolon_newline(self):
        """When no blank line, should break at semicolon + newline."""
        # Generate code with semicolons (like Java)
        lines = [f"int x{i} = {i};" for i in range(500)]
        code = "\n".join(lines)
        if len(code) > MAX_CODE_SNIPPET_CHARS:
            result = _smart_truncate(code)
            assert len(result) <= MAX_CODE_SNIPPET_CHARS
            # Should end at a semicolon-newline boundary
            assert ";" in result[-20:]

    def test_long_code_truncates_at_newline(self):
        """When no blank line or semicolon, should break at newline."""
        # Generate code without semicolons or blank lines
        lines = [f"x{i} = {i}" for i in range(500)]
        code = "\n".join(lines)
        if len(code) > MAX_CODE_SNIPPET_CHARS:
            result = _smart_truncate(code)
            assert len(result) <= MAX_CODE_SNIPPET_CHARS
            assert result.endswith("\n")

    def test_no_break_point_hard_cut(self):
        """When no break point found, should do a hard cut at max_chars."""
        code = "a" * (MAX_CODE_SNIPPET_CHARS + 500)  # No newlines at all
        result = _smart_truncate(code)
        assert len(result) == MAX_CODE_SNIPPET_CHARS

    def test_custom_max_chars(self):
        """Should respect custom max_chars parameter."""
        code = "line1\nline2\nline3\nline4\n"
        result = _smart_truncate(code, max_chars=10)
        assert len(result) <= 10

    def test_empty_string(self):
        """Empty string should be returned as-is."""
        assert _smart_truncate("") == ""

    def test_default_limit_is_3000(self):
        """Default limit should be 3000 chars."""
        assert MAX_CODE_SNIPPET_CHARS == 3000
