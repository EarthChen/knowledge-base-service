"""Phase 2 integration: navigation context, summaries, depth collection."""

from wiki.models import PageType, WikiPage, WikiPageMetadata, WikiStructureNode
from wiki.service import (
    _collect_nodes_by_depth,
    _extract_summary,
    _populate_navigation_context,
)


def test_extract_summary_integration() -> None:
    """Verify extract_summary works with realistic content."""
    page = WikiPage(
        path="classes/Auth.md",
        title="Auth",
        page_type=PageType.CLASS_DETAIL,
        content="# Auth\n\n## Overview\n\nAuthentication service handling OAuth2 and JWT tokens.\n\n## Methods\n...",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(5, 3),
    )
    summary = _extract_summary(page, entity_uid="uid:Class:Auth")
    assert summary.entity_uid == "uid:Class:Auth"
    assert "OAuth2" in summary.summary or "Authentication" in summary.summary
    assert summary.page_type == PageType.CLASS_DETAIL


def test_collect_nodes_deep_tree() -> None:
    """Verify bottom-up ordering with 3-level tree."""
    c1 = WikiStructureNode(path="classes/C1.md", title="C1", page_type=PageType.CLASS_DETAIL)
    c2 = WikiStructureNode(path="classes/C2.md", title="C2", page_type=PageType.CLASS_DETAIL)
    c3 = WikiStructureNode(path="classes/C3.md", title="C3", page_type=PageType.CLASS_DETAIL)
    mod_a = WikiStructureNode(
        path="modules/a",
        title="a",
        page_type=PageType.MODULE_OVERVIEW,
        children=[c1, c2],
    )
    mod_b = WikiStructureNode(
        path="modules/b",
        title="b",
        page_type=PageType.MODULE_OVERVIEW,
        children=[c3],
    )
    root = WikiStructureNode(
        path="README.md",
        title="repo",
        page_type=PageType.REPO_OVERVIEW,
        children=[mod_a, mod_b],
    )

    leaves, parents = _collect_nodes_by_depth(root)
    assert len(leaves) == 3
    assert len(parents) == 3
    parent_paths = [p[1].path for p in parents]
    root_idx = parent_paths.index("README.md")
    assert root_idx == len(parents) - 1


def test_populate_navigation_full_tree() -> None:
    """Verify full navigation context for a realistic tree."""
    c1 = WikiStructureNode(path="classes/C1.md", title="C1", page_type=PageType.CLASS_DETAIL)
    c2 = WikiStructureNode(path="classes/C2.md", title="C2", page_type=PageType.CLASS_DETAIL)
    mod_a = WikiStructureNode(
        path="modules/a",
        title="a",
        page_type=PageType.MODULE_OVERVIEW,
        children=[c1, c2],
    )
    root = WikiStructureNode(
        path="README.md",
        title="repo",
        page_type=PageType.REPO_OVERVIEW,
        children=[mod_a],
    )

    pages = {
        "classes/C1.md": WikiPage(
            path="classes/C1.md",
            title="C1",
            page_type=PageType.CLASS_DETAIL,
            content="# C1",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(1, 1),
        ),
        "classes/C2.md": WikiPage(
            path="classes/C2.md",
            title="C2",
            page_type=PageType.CLASS_DETAIL,
            content="# C2",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(1, 1),
        ),
        "modules/a": WikiPage(
            path="modules/a",
            title="a",
            page_type=PageType.MODULE_OVERVIEW,
            content="# a",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(2, 2),
        ),
    }
    _populate_navigation_context(root, pages)
    nav_c1 = pages["classes/C1.md"].navigation
    assert nav_c1 is not None
    assert nav_c1.parent_path == "modules/a"
    assert "classes/C2.md" in nav_c1.sibling_paths
    nav_a = pages["modules/a"].navigation
    assert nav_a is not None
    assert nav_a.parent_path == "README.md"
    assert set(nav_a.child_paths) == {"classes/C1.md", "classes/C2.md"}
