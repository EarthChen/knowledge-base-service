"""Tests for wiki hierarchical generation model additions (Phase 1)."""

from wiki.models import (
    ImportanceTier,
    NavigationContext,
    PageType,
    SkeletonStrategy,
    WikiPageSummary,
    WikiStructureNode,
)


def test_skeleton_strategy_values():
    assert SkeletonStrategy.TEMPLATE == "template"
    assert SkeletonStrategy.LIGHT_MODEL == "light_model"
    assert SkeletonStrategy.SKIP == "skip"


def test_wiki_page_summary_creation():
    summary = WikiPageSummary(
        entity_uid="uid:Class:MyClass",
        title="MyClass",
        path="classes/MyClass.md",
        summary="A core service class that handles...",
        importance_tier=ImportanceTier.CORE,
        page_type=PageType.CLASS_DETAIL,
    )
    assert summary.title == "MyClass"
    assert summary.importance_tier == ImportanceTier.CORE


def test_navigation_context_defaults():
    nav = NavigationContext()
    assert nav.parent_path is None
    assert nav.sibling_paths == []
    assert nav.breadcrumbs == []


def test_navigation_context_with_data():
    nav = NavigationContext(
        parent_path="modules/api",
        parent_title="api",
        sibling_paths=["classes/Bar.md"],
        child_paths=[],
        breadcrumbs=[("repo", "README.md"), ("api", "modules/api")],
    )
    assert nav.parent_title == "api"
    assert len(nav.breadcrumbs) == 2


def test_wiki_structure_node_is_leaf():
    leaf = WikiStructureNode(path="classes/Foo.md", title="Foo", page_type=PageType.CLASS_DETAIL)
    parent = WikiStructureNode(
        path="modules/bar",
        title="bar",
        page_type=PageType.MODULE_OVERVIEW,
        children=[leaf],
    )
    assert leaf.is_leaf is True
    assert parent.is_leaf is False
