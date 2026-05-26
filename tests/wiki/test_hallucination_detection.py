from __future__ import annotations


class TestHallucinationDetection:
    def test_extract_class_references(self):
        from wiki.nodes.finalize import _extract_class_references

        content = "Uses `FamilyTaskService` and `FamilyChestService` for business logic. Also `someVar` is used."
        refs = _extract_class_references(content)
        assert "FamilyTaskService" in refs
        assert "FamilyChestService" in refs
        assert "someVar" not in refs

    def test_remove_invalid_wikilinks(self):
        from wiki.nodes.finalize import _remove_invalid_wikilinks

        content = "See [[家族任务系统]] and [[不存在的页面]] for details."
        valid = {"家族任务系统"}
        result = _remove_invalid_wikilinks(content, valid)
        assert "[[家族任务系统]]" in result
        assert "[[不存在的页面]]" not in result
        assert "不存在的页面" in result

    def test_no_wikilinks_unchanged(self):
        from wiki.nodes.finalize import _remove_invalid_wikilinks

        content = "No links here."
        result = _remove_invalid_wikilinks(content, set())
        assert result == "No links here."
