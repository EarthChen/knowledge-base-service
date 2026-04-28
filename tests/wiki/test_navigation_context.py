import pytest
from wiki.service import _populate_navigation_context
from wiki.models import WikiPage, WikiPageMetadata, WikiStructureNode, PageType


def _make_structure():
    """Build: root > module_a > [class_foo, class_bar]"""
    foo = WikiStructureNode(path="classes/Foo.md", title="Foo", page_type=PageType.CLASS_DETAIL)
    bar = WikiStructureNode(path="classes/Bar.md", title="Bar", page_type=PageType.CLASS_DETAIL)
    mod_a = WikiStructureNode(
        path="modules/api",
        title="api",
        page_type=PageType.MODULE_OVERVIEW,
        children=[foo, bar],
    )
    root = WikiStructureNode(
        path="README.md",
        title="repo",
        page_type=PageType.REPO_OVERVIEW,
        children=[mod_a],
    )
    return root


def test_populate_navigation_breadcrumbs():
    root = _make_structure()
    pages = {
        "classes/Foo.md": WikiPage(
            path="classes/Foo.md",
            title="Foo",
            page_type=PageType.CLASS_DETAIL,
            content="# Foo",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(1, 1),
        ),
    }
    _populate_navigation_context(root, pages)
    foo_page = pages["classes/Foo.md"]
    nav = foo_page.navigation
    assert nav is not None
    assert nav.parent_path == "modules/api"
    assert nav.parent_title == "api"
    assert len(nav.breadcrumbs) >= 2
    assert "classes/Bar.md" in nav.sibling_paths


def test_populate_navigation_root_has_no_parent():
    root = _make_structure()
    pages = {
        "README.md": WikiPage(
            path="README.md",
            title="repo",
            page_type=PageType.REPO_OVERVIEW,
            content="# repo",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(0, 0),
        ),
    }
    _populate_navigation_context(root, pages)
    assert pages["README.md"].navigation.parent_path is None


def test_populate_navigation_child_paths():
    root = _make_structure()
    pages = {
        "modules/api": WikiPage(
            path="modules/api",
            title="api",
            page_type=PageType.MODULE_OVERVIEW,
            content="# api",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(0, 0),
        ),
    }
    _populate_navigation_context(root, pages)
    nav = pages["modules/api"].navigation
    assert "classes/Foo.md" in nav.child_paths
    assert "classes/Bar.md" in nav.child_paths


def test_populate_navigation_skips_missing_pages():
    root = _make_structure()
    pages = {}  # no pages at all
    _populate_navigation_context(root, pages)  # should not crash
