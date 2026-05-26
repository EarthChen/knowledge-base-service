from __future__ import annotations

from wiki.quality_report import _count_module_inline_refs, _is_module_covered, evaluate_quality


class TestCompoundKeyCoverage:
    def test_compound_key_matched(self):
        content = "The FamilyPowerService handles power management."
        assert _is_module_covered(content, "ultron|FamilyPowerService") is True

    def test_compound_key_unmatched(self):
        content = "This page covers UserService only."
        assert _is_module_covered(content, "ultron|FamilyPowerService") is False

    def test_simple_name_still_works(self):
        content = "The FamilyPowerService handles power."
        assert _is_module_covered(content, "FamilyPowerService") is True

    def test_dotted_name_still_works(self):
        content = "The PowerService is important."
        assert _is_module_covered(content, "com.family.PowerService") is True

    def test_compound_key_with_dot(self):
        content = "The PowerService is important."
        assert _is_module_covered(content, "ultron|com.family.PowerService") is True


class TestCompoundKeyEvaluateQuality:
    def test_coverage_with_compound_keys(self):
        content = "# Overview\n\n`FamilyPowerService` and `UserService` are key modules.\n\n```java\ncode\n```"
        modules = ["ultron|FamilyPowerService", "ultron|UserService", "ultron|MissingService"]
        report = evaluate_quality(content, modules)
        assert report.coverage >= 0.6  # 2/3 covered

    def test_coverage_without_compound_keys(self):
        content = "# Overview\n\nFamilyPowerService is covered."
        modules = ["FamilyPowerService"]
        report = evaluate_quality(content, modules)
        assert report.coverage == 1.0


class TestCompoundKeyInlineRefs:
    def test_inline_ref_with_compound_key(self):
        content = "Use `FamilyPowerService` for this."
        count = _count_module_inline_refs(content, ["ultron|FamilyPowerService"])
        assert count >= 1
