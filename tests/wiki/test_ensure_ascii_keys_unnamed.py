"""Tests for _ensure_ascii_keys rejecting 'unnamed' slug."""

from __future__ import annotations

from wiki.nodes.classify import _ensure_ascii_keys


class TestEnsureAsciiKeysUnnamed:
    def test_unnamed_key_is_replaced(self):
        mapping = {
            "unnamed": [
                ("repo", "com.example.TypeHandler"),
                ("repo", "com.example.AopConfig"),
            ],
        }
        display = {"unnamed": "数据类型转换"}
        result_mapping, _ = _ensure_ascii_keys(mapping, display)
        assert "unnamed" not in result_mapping, "'unnamed' key should be replaced"
        keys = list(result_mapping.keys())
        assert len(keys) == 1
        assert keys[0] != "unnamed"

    def test_valid_ascii_key_unchanged(self):
        mapping = {
            "user-management": [("repo", "com.user.Service")],
        }
        display = {"user-management": "用户管理"}
        result_mapping, _ = _ensure_ascii_keys(mapping, display)
        assert "user-management" in result_mapping
