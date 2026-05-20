# tests/wiki/test_navigation_context.py
from __future__ import annotations

import pytest
from wiki.nodes.links import create_links_node


@pytest.mark.asyncio
async def test_navigation_context_populated_for_domain_pages():
    """Domain overview pages get parent_path, child_paths, sibling_paths."""
    state = {
        "pages": [
            {
                "path": "/__domains__/parent-domain/_overview",
                "title": "Parent Domain",
                "content": "# Parent\n[[Child A]] [[Child B]]",
                "page_type": "domain_overview",
            },
            {
                "path": "/__domains__/child-a/_overview",
                "title": "Child A",
                "content": "# Child A overview",
                "page_type": "domain_overview",
            },
            {
                "path": "/__domains__/child-b/_overview",
                "title": "Child B",
                "content": "# Child B overview",
                "page_type": "domain_overview",
            },
        ],
        "domain_tree": [
            {
                "name": "parent-domain",
                "display_name": "Parent Domain",
                "modules": [],
                "children": [
                    {"name": "child-a", "display_name": "Child A", "modules": ["ModA"], "children": []},
                    {"name": "child-b", "display_name": "Child B", "modules": ["ModB"], "children": []},
                ],
            },
        ],
    }
    result = await create_links_node(state)

    pages = state["pages"]
    parent_page = next(p for p in pages if p["path"] == "/__domains__/parent-domain/_overview")
    child_a = next(p for p in pages if p["path"] == "/__domains__/child-a/_overview")

    parent_nav = parent_page.get("navigation", {})
    assert "/__domains__/child-a/_overview" in parent_nav.get("child_paths", [])
    assert "/__domains__/child-b/_overview" in parent_nav.get("child_paths", [])
    assert parent_nav.get("parent_path", "") == ""

    child_nav = child_a.get("navigation", {})
    assert child_nav.get("parent_path") == "/__domains__/parent-domain/_overview"
    assert child_nav.get("parent_title") == "Parent Domain"
    assert "/__domains__/child-b/_overview" in child_nav.get("sibling_paths", [])

    parent_crumbs = parent_nav.get("breadcrumbs", [])
    assert parent_crumbs == [["Parent Domain", "/__domains__/parent-domain/_overview"]]

    child_crumbs = child_nav.get("breadcrumbs", [])
    assert child_crumbs == [
        ["Parent Domain", "/__domains__/parent-domain/_overview"],
        ["Child A", "/__domains__/child-a/_overview"],
    ]


@pytest.mark.asyncio
async def test_navigation_context_topic_pages():
    """Topic pages get parent_path pointing to their domain overview."""
    state = {
        "pages": [
            {
                "path": "/__domains__/my-domain/_overview",
                "title": "My Domain",
                "content": "# My Domain",
                "page_type": "domain_overview",
            },
            {
                "path": "/__domains__/my-domain/topic-a/_topic",
                "title": "Topic A",
                "content": "# Topic A",
                "page_type": "topic",
            },
        ],
        "domain_tree": [
            {
                "name": "my-domain",
                "display_name": "My Domain",
                "modules": ["ModA", "ModB"],
                "children": [],
            },
        ],
    }
    result = await create_links_node(state)

    topic_page = state["pages"][1]
    topic_nav = topic_page.get("navigation", {})
    assert topic_nav.get("parent_path") == "/__domains__/my-domain/_overview"
    assert topic_nav.get("parent_title") == "My Domain"
    assert topic_nav.get("breadcrumbs") == [
        ["My Domain", "/__domains__/my-domain/_overview"],
        ["Topic A", "/__domains__/my-domain/topic-a/_topic"],
    ]
