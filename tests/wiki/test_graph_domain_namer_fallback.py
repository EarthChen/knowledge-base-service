from __future__ import annotations

from wiki.graph_domain_namer import _fallback_name


class TestFallbackNameModuleDerived:
    def test_dotted_modules_uses_short_names(self):
        result = _fallback_name(["com.family.FamilyPowerService", "com.family.FamilyRankService"])
        assert result["slug"] != "unnamed"
        assert result["slug"].isascii()
        # Should derive from the Family prefix stripped of tech suffixes
        assert "family" in result["slug"].lower()

    def test_empty_modules_returns_unnamed(self):
        result = _fallback_name([])
        assert result["slug"] == "unnamed"
        assert result["display_name"] == "unnamed"

    def test_single_module_uses_stripped_name(self):
        result = _fallback_name(["OrderService"])
        slug = result["slug"]
        assert slug != "unnamed"
        assert "order" in slug.lower()

    def test_modules_with_common_prefix(self):
        result = _fallback_name(["PaymentService", "PaymentHandler", "PaymentDao"])
        assert "payment" in result["slug"].lower()

    def test_camelcase_only_modules(self):
        result = _fallback_name(["FamilyPowerService", "FamilyRankService"])
        assert result["slug"] != "unnamed"
        assert "family" in result["slug"].lower()

    def test_no_camelcase_words_falls_back_to_short_name(self):
        # Module names that don't have CamelCase words (e.g. all lowercase)
        result = _fallback_name(["abc_helper", "def_util"])
        # Should still produce a valid slug (not "unnamed")
        assert result["slug"].isascii()
