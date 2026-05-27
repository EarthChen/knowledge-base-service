import pytest
from wiki.path_conventions import normalize_slug, domain_overview_path, domain_topic_path


class TestNormalizeSlug:
    def test_basic_kebab(self):
        assert normalize_slug("gift-system") == "gift-system"

    def test_spaces_to_hyphens(self):
        assert normalize_slug("gift system") == "gift-system"

    def test_mixed_ascii_strip(self):
        assert normalize_slug("Gift_System v2") == "gift-system-v2"

    def test_consecutive_hyphens(self):
        assert normalize_slug("gift--system") == "gift-system"

    def test_leading_trailing_hyphens(self):
        assert normalize_slug("-gift-system-") == "gift-system"

    def test_uppercase_to_lower(self):
        assert normalize_slug("GiftSystem") == "gift-system"

    def test_empty_returns_unnamed(self):
        assert normalize_slug("") == "unnamed"

    def test_chinese_only_returns_unnamed(self):
        result = normalize_slug("礼物系统")
        assert result == "unnamed"


class TestSlugPaths:
    def test_domain_overview_path_slug(self):
        assert domain_overview_path("gift-system") == "/__domains__/gift-system/_overview"

    def test_domain_topic_path_slug(self):
        assert domain_topic_path("gift-system", "order-flow") == "/__domains__/gift-system/order-flow/_topic"
