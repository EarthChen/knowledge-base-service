# tests/wiki/test_wikilink_converter.py
"""Unit tests for WikiLinkConverter."""

from wiki.wikilink_converter import WikiLinkConverter


class TestToMarkdown:
    def test_same_directory_sibling(self):
        conv = WikiLinkConverter()
        content = "See [[/domain/sibling]] for details."
        result = conv.to_markdown(content, current_path="/domain/page")
        assert "[sibling](sibling.md)" in result
        assert "[[" not in result

    def test_cross_directory(self):
        conv = WikiLinkConverter()
        content = "Calls [[/other/target]]."
        result = conv.to_markdown(content, current_path="/domain/page")
        assert "[target](../other/target.md)" in result

    def test_overview_maps_to_readme(self):
        conv = WikiLinkConverter()
        content = "See [[/domain/_overview]]."
        result = conv.to_markdown(content, current_path="/other/page")
        assert "domain/README.md" in result

    def test_no_wikilinks_passthrough(self):
        conv = WikiLinkConverter()
        content = "No links here."
        result = conv.to_markdown(content, current_path="/a/b")
        assert result == content

    def test_multiple_wikilinks_in_one_line(self):
        conv = WikiLinkConverter()
        content = "Uses [[/a/X]] and [[/b/Y]]."
        result = conv.to_markdown(content, current_path="/c/page")
        assert "[[" not in result
        assert "[X](" in result
        assert "[Y](" in result

    def test_root_overview_maps_to_readme(self):
        conv = WikiLinkConverter()
        content = "See [[/_overview]]."
        result = conv.to_markdown(content, current_path="/domain/page")
        assert "README.md" in result
        assert "[[" not in result

    def test_deeply_nested_path(self):
        conv = WikiLinkConverter()
        content = "See [[/用户管理/注册流程/UserController]]."
        result = conv.to_markdown(content, current_path="/订单处理/page")
        assert "UserController" in result
        assert ".md" in result
        assert "[[" not in result


class TestToObsidian:
    def test_strips_leading_slash(self):
        conv = WikiLinkConverter()
        content = "See [[/domain/UserService]]."
        result = conv.to_obsidian(content)
        assert "[[domain/UserService]]" in result
        assert "[[/" not in result

    def test_preserves_double_brackets(self):
        conv = WikiLinkConverter()
        content = "See [[/a/B]]."
        result = conv.to_obsidian(content)
        assert "[[a/B]]" in result

    def test_no_wikilinks_passthrough(self):
        conv = WikiLinkConverter()
        content = "Plain text."
        result = conv.to_obsidian(content)
        assert result == content

    def test_unicode_path(self):
        conv = WikiLinkConverter()
        content = "See [[/用户管理/UserService]]."
        result = conv.to_obsidian(content)
        assert "[[用户管理/UserService]]" in result


class TestExtractWikilinks:
    def test_extract_multiple(self):
        conv = WikiLinkConverter()
        content = "See [[/a/X]] and [[/b/Y]]."
        links = conv.extract_wikilinks(content)
        assert "/a/X" in links
        assert "/b/Y" in links

    def test_extract_empty_content(self):
        conv = WikiLinkConverter()
        links = conv.extract_wikilinks("No links.")
        assert links == []
