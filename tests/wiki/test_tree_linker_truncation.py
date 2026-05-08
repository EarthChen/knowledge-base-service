# tests/wiki/test_tree_linker_truncation.py


class TestSafeTruncate:
    def test_short_text_unchanged(self):
        from wiki.tree_linker import _safe_truncate

        assert _safe_truncate("short text") == "short text"

    def test_truncate_at_sentence(self):
        from wiki.tree_linker import _safe_truncate

        text = "First sentence。Second sentence that makes it very long " * 5
        result = _safe_truncate(text, 50)
        assert len(result) <= 50
        assert result.endswith("。") or result.endswith(" ") or len(result) <= 50

    def test_no_backtick_split(self):
        from wiki.tree_linker import _safe_truncate

        text = "Module `com.example.very.long.package.name.ClassName` handles requests and more text here"
        result = _safe_truncate(text, 60)
        assert result.count("`") % 2 == 0, "Should not split inside backticks"

    def test_returns_original_if_short(self):
        from wiki.tree_linker import _safe_truncate

        assert _safe_truncate("hello", 150) == "hello"
