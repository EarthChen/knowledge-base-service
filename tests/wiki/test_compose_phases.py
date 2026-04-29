import inspect

from wiki.service import _extract_summary, _collect_nodes_by_depth
from wiki.models import WikiPage, WikiPageMetadata, PageType, WikiStructureNode


def test_extract_summary_from_overview_section():
    page = WikiPage(
        path="classes/Foo.md",
        title="Foo",
        page_type=PageType.CLASS_DETAIL,
        content="# Foo\n\n## Overview\n\nFoo handles authentication and session management.\n\n## Methods\n...",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    summary = _extract_summary(page, entity_uid="uid:Class:Foo")
    assert summary.title == "Foo"
    assert summary.entity_uid == "uid:Class:Foo"
    assert "authentication" in summary.summary
    assert len(summary.summary) <= 200


def test_extract_summary_no_overview():
    page = WikiPage(
        path="fn/bar.md",
        title="bar",
        page_type=PageType.API_REFERENCE,
        content="# bar\n\nA utility function that processes input data.\n\nDetails...",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(0, 0),
    )
    summary = _extract_summary(page, entity_uid="uid:Fn:bar")
    assert "utility" in summary.summary


def test_extract_summary_empty_content():
    page = WikiPage(
        path="test.md",
        title="test",
        page_type=PageType.CLASS_DETAIL,
        content="",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(0, 0),
    )
    summary = _extract_summary(page, entity_uid="uid:test")
    assert summary.summary == ""


def test_collect_nodes_leaves_and_parents():
    foo = WikiStructureNode(path="classes/Foo.md", title="Foo", page_type=PageType.CLASS_DETAIL)
    bar = WikiStructureNode(path="classes/Bar.md", title="Bar", page_type=PageType.CLASS_DETAIL)
    mod_a = WikiStructureNode(
        path="modules/api", title="api", page_type=PageType.MODULE_OVERVIEW, children=[foo, bar]
    )
    root = WikiStructureNode(
        path="README.md", title="repo", page_type=PageType.REPO_OVERVIEW, children=[mod_a]
    )

    leaves, parents = _collect_nodes_by_depth(root)
    assert len(leaves) == 2
    assert {l.path for l in leaves} == {"classes/Foo.md", "classes/Bar.md"}
    assert len(parents) == 2  # root + mod_a
    # Deepest first: mod_a (depth=1) before root (depth=0)
    assert parents[0][1].path == "modules/api"
    assert parents[1][1].path == "README.md"


def test_collect_nodes_flat_structure():
    leaf = WikiStructureNode(path="fn/main.md", title="main", page_type=PageType.CLASS_DETAIL)
    root = WikiStructureNode(
        path="README.md", title="repo", page_type=PageType.REPO_OVERVIEW, children=[leaf]
    )
    leaves, parents = _collect_nodes_by_depth(root)
    assert len(leaves) == 1
    assert len(parents) == 1


class TestParentComposeV2:
    def test_parent_prompt_mentions_architecture(self):
        """V2 system prompt should mention architecture."""
        from wiki.composer import _PARENT_SYSTEM_PROMPT

        assert "Architecture" in _PARENT_SYSTEM_PROMPT or "architect" in _PARENT_SYSTEM_PROMPT.lower()

    def test_compose_parent_accepts_inter_child_edges(self):
        """compose_parent_page should accept inter_child_edges parameter."""
        from wiki.composer import WikiComposer

        sig = inspect.signature(WikiComposer.compose_parent_page)
        assert "inter_child_edges" in sig.parameters


class TestGlossaryAlignment:
    def test_glossary_accepts_two_string_lists(self):
        """build_glossary should accept module_names and entry_points as lists of strings."""
        from wiki.context import WikiContextBuilder

        sig = inspect.signature(WikiContextBuilder.build_glossary)
        params = list(sig.parameters.keys())
        assert len(params) >= 3  # self + 2 params
