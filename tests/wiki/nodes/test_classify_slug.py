from __future__ import annotations

from wiki.nodes.classify import _ensure_ascii_keys


class TestEnsureAsciiKeysModuleDerived:
    def test_chinese_key_derives_from_modules(self):
        mapping = {"家族系统": [("ultron", "FamilyPowerService"), ("ultron", "FamilyRankService")]}
        display = {"家族系统": "家族系统"}
        result_mapping, result_display = _ensure_ascii_keys(mapping, display)
        keys = list(result_mapping.keys())
        assert len(keys) == 1
        slug = keys[0]
        assert not slug.startswith("domain-"), f"Expected module-derived slug, got {slug}"
        assert slug.isascii()
        assert "family-power-service" in slug.lower() or "family-rank-service" in slug.lower()

    def test_chinese_key_no_modules_falls_back_to_misc(self):
        mapping = {"空域": []}
        display = {"空域": "空域"}
        result_mapping, _ = _ensure_ascii_keys(mapping, display)
        slug = list(result_mapping.keys())[0]
        assert slug.startswith("misc-"), f"Expected misc-NN, got {slug}"

    def test_ascii_key_unchanged(self):
        mapping = {"payment": [("ultron", "PayService")]}
        display = {"payment": "支付"}
        result_mapping, _ = _ensure_ascii_keys(mapping, display)
        assert "payment" in result_mapping

    def test_collision_resolved_with_different_modules(self):
        mapping = {
            "域A": [("ultron", "ServiceA")],
            "域B": [("ultron", "ServiceB")],
        }
        display = {"域A": "域A", "域B": "域B"}
        result_mapping, _ = _ensure_ascii_keys(mapping, display)
        keys = list(result_mapping.keys())
        assert len(keys) == 2
        assert keys[0] != keys[1], "Slugs should be unique"

    def test_display_name_preserved(self):
        mapping = {"用户系统": [("repo", "UserService")]}
        display = {"用户系统": "用户系统"}
        _, result_display = _ensure_ascii_keys(mapping, display)
        # The original Chinese name should be preserved in display names
        assert any("用户系统" in v for v in result_display.values())
