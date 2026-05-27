"""Tests for slug normalization edge cases — unnamed, CJK, empty, camelCase."""

from __future__ import annotations

import pytest

from wiki.path_conventions import normalize_slug, normalize_slug_strict


class TestCamelCaseSplitting:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("MemberStatisticsAccount", "member-statistics-account"),
            ("IMOneLink", "im-one-link"),
            ("EsClient", "es-client"),
            ("AbsClosedFriendTaskExecutor", "abs-closed-friend-task-executor"),
            ("already-kebab-case", "already-kebab-case"),
            ("simple", "simple"),
            ("XMLParser", "xml-parser"),
            ("getUserById", "get-user-by-id"),
        ],
    )
    def test_normalize_slug_camel_case(self, raw: str, expected: str) -> None:
        assert normalize_slug(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("MemberStatisticsAccount", "member-statistics-account"),
            ("IMOneLink", "im-one-link"),
            ("EsClient", "es-client"),
            ("AbsClosedFriendTaskExecutor", "abs-closed-friend-task-executor"),
            ("already-kebab-case", "already-kebab-case"),
            ("simple", "simple"),
            ("XMLParser", "xml-parser"),
            ("getUserById", "get-user-by-id"),
        ],
    )
    def test_normalize_slug_strict_camel_case(self, raw: str, expected: str) -> None:
        assert normalize_slug_strict(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "数据持久化类型转换"])
    def test_normalize_slug_strict_empty_or_cjk_returns_none(self, raw: str) -> None:
        assert normalize_slug_strict(raw) is None


class TestNormalizeSlugStrict:
    def test_chinese_input_returns_none(self):
        assert normalize_slug_strict("数据持久化类型转换") is None

    def test_mixed_chinese_english(self):
        assert normalize_slug_strict("用户data管理") == "data"

    def test_english_input(self):
        assert normalize_slug_strict("user-management") == "user-management"

    def test_empty_string(self):
        assert normalize_slug_strict("") is None

    def test_spaces_only(self):
        assert normalize_slug_strict("   ") is None

    def test_existing_normalize_slug_unchanged(self):
        # Original normalize_slug still returns "unnamed" for backward compat
        assert normalize_slug("数据持久化") == "unnamed"
        assert normalize_slug("hello-world") == "hello-world"
