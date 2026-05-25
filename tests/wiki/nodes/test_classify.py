"""Tests for prefix extraction helpers used by domain consolidation."""

from __future__ import annotations

from wiki.nodes.classify import _extract_prefix


class TestExtractPrefix:
    def test_db_util_prefix(self):
        assert _extract_prefix("DbUtil") == "Db"

    def test_io_handler_prefix(self):
        assert _extract_prefix("IoHandler") == "Io"

    def test_snake_case_user_service(self):
        assert _extract_prefix("user_service") == "User"

    def test_generic_base_controller_none(self):
        assert _extract_prefix("BaseController") is None

    def test_all_caps_io_handler(self):
        """IOHandler should still extract IO (all-caps acronym prefix)."""
        assert _extract_prefix("IOHandler") == "IO"
