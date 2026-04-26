"""Tests for WikiReferenceGenerator (code-graph → WIKI_REFERENCES)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from store.falkordb_store import QueryResultWrapper
from wiki.reference_generator import WikiReferenceGenerator


@pytest.mark.asyncio
async def test_generates_calls_reference():
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(
        return_value=[
            {
                "wiki_uid": "wp:svc:A",
                "entity_uid": "fn:A",
                "path": "/svc/A.md",
                "repository": "svc",
            },
            {
                "wiki_uid": "wp:svc:B",
                "entity_uid": "fn:B",
                "path": "/svc/B.md",
                "repository": "svc",
            },
        ],
    )
    store.find_code_entity_relationships = AsyncMock(
        return_value=[
            {"source_uid": "fn:A", "target_uid": "fn:B", "rel_type": "CALLS"},
        ],
    )
    store.add_wiki_reference_edge = AsyncMock(
        return_value=QueryResultWrapper([{"rel": "WIKI_REFERENCES"}], []),
    )

    gen = WikiReferenceGenerator(store)
    await gen.generate(repository="svc")

    store.add_wiki_reference_edge.assert_awaited_once_with(
        "wp:svc:A",
        "wp:svc:B",
        "calls",
        context="",
        auto_generated=True,
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_generates_cross_repo_reference():
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(
        return_value=[
            {
                "wiki_uid": "wp:a:X",
                "entity_uid": "e:X",
                "path": "/a/X.md",
                "repository": "repo-a",
            },
            {
                "wiki_uid": "wp:b:Y",
                "entity_uid": "e:Y",
                "path": "/b/Y.md",
                "repository": "repo-b",
            },
        ],
    )
    store.find_code_entity_relationships = AsyncMock(
        return_value=[
            {"source_uid": "e:X", "target_uid": "e:Y", "rel_type": "CROSS_REPO_CALLS"},
        ],
    )
    store.add_wiki_reference_edge = AsyncMock(
        return_value=QueryResultWrapper([], []),
    )

    gen = WikiReferenceGenerator(store)
    await gen.generate()

    store.add_wiki_reference_edge.assert_awaited_once_with(
        "wp:a:X",
        "wp:b:Y",
        "cross_repo",
        context="",
        auto_generated=True,
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_generates_inherits_reference():
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(
        return_value=[
            {
                "wiki_uid": "wp:Child",
                "entity_uid": "cls:Child",
                "path": "/Child.md",
                "repository": "svc",
            },
            {
                "wiki_uid": "wp:Parent",
                "entity_uid": "cls:Parent",
                "path": "/Parent.md",
                "repository": "svc",
            },
        ],
    )
    store.find_code_entity_relationships = AsyncMock(
        return_value=[
            {"source_uid": "cls:Child", "target_uid": "cls:Parent", "rel_type": "INHERITS"},
        ],
    )
    store.add_wiki_reference_edge = AsyncMock(
        return_value=QueryResultWrapper([], []),
    )

    gen = WikiReferenceGenerator(store)
    await gen.generate()

    store.add_wiki_reference_edge.assert_awaited_once_with(
        "wp:Child",
        "wp:Parent",
        "inherits",
        context="",
        auto_generated=True,
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_no_self_reference():
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(
        return_value=[
            {
                "wiki_uid": "wp:same",
                "entity_uid": "fn:loop",
                "path": "/loop.md",
                "repository": "svc",
            },
        ],
    )
    store.find_code_entity_relationships = AsyncMock(
        return_value=[
            {"source_uid": "fn:loop", "target_uid": "fn:loop", "rel_type": "CALLS"},
        ],
    )
    store.add_wiki_reference_edge = AsyncMock(
        return_value=QueryResultWrapper([], []),
    )

    gen = WikiReferenceGenerator(store)
    await gen.generate()

    store.add_wiki_reference_edge.assert_not_awaited()


@pytest.mark.asyncio
async def test_deduplicates_references():
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(
        return_value=[
            {
                "wiki_uid": "wp:1",
                "entity_uid": "e:1",
                "path": "/1.md",
                "repository": "svc",
            },
            {
                "wiki_uid": "wp:2",
                "entity_uid": "e:2",
                "path": "/2.md",
                "repository": "svc",
            },
        ],
    )
    store.find_code_entity_relationships = AsyncMock(
        return_value=[
            {"source_uid": "e:1", "target_uid": "e:2", "rel_type": "CALLS"},
            {"source_uid": "e:1", "target_uid": "e:2", "rel_type": "CALLS"},
        ],
    )
    store.add_wiki_reference_edge = AsyncMock(
        return_value=QueryResultWrapper([], []),
    )

    gen = WikiReferenceGenerator(store)
    await gen.generate()

    assert store.add_wiki_reference_edge.await_count == 1
    store.add_wiki_reference_edge.assert_awaited_with(
        "wp:1",
        "wp:2",
        "calls",
        context="",
        auto_generated=True,
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_no_pages_returns_empty():
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(return_value=[])
    store.find_code_entity_relationships = AsyncMock(return_value=[])
    store.add_wiki_reference_edge = AsyncMock(
        return_value=QueryResultWrapper([], []),
    )

    gen = WikiReferenceGenerator(store)
    await gen.generate(repository="empty-repo")

    store.find_code_entity_relationships.assert_not_awaited()
    store.add_wiki_reference_edge.assert_not_awaited()


def test_inject_wikilinks_adds_related_section():
    gen = WikiReferenceGenerator(AsyncMock())
    content = "# Title\n\nBody."
    result = gen.inject_wikilinks(content, ["/a.md", "/b.md"])
    assert result.endswith(
        "\n\n## Related Pages\n- [[/a.md]]\n- [[/b.md]]"
    )
    assert result.startswith("# Title\n\nBody.")


def test_inject_wikilinks_empty_refs_no_change():
    gen = WikiReferenceGenerator(AsyncMock())
    content = "# Only\n\nText.\n"
    assert gen.inject_wikilinks(content, []) == content
    assert gen.inject_wikilinks(content, ["", "  "]) == content
    assert gen.inject_wikilinks(content, [{"path": ""}, {}]) == content


def test_inject_wikilinks_deduplicates_paths():
    gen = WikiReferenceGenerator(AsyncMock())
    content = "Intro"
    result = gen.inject_wikilinks(
        content,
        ["/x.md", "/x.md", {"path": "/x.md"}, "/y.md", "/y.md"],
    )
    assert result.count("[[/x.md]]") == 1
    assert result.count("[[/y.md]]") == 1
    assert "## Related Pages" in result


@pytest.mark.asyncio
async def test_generate_skips_relationship_query_when_mappings_have_no_uids():
    """Mappings without entity_uid/wiki_uid pairs must not call unfiltered relationship scan."""
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(
        return_value=[
            {"wiki_uid": "", "entity_uid": "e:1", "path": "/1.md", "repository": "svc"},
            {"wiki_uid": "wp:1", "entity_uid": "", "path": "/1.md", "repository": "svc"},
        ],
    )
    store.find_code_entity_relationships = AsyncMock(return_value=[])
    store.add_wiki_reference_edge = AsyncMock(
        return_value=QueryResultWrapper([], []),
    )

    gen = WikiReferenceGenerator(store)
    count = await gen.generate(repository="svc")

    assert count == 0
    store.find_code_entity_relationships.assert_not_awaited()
    store.add_wiki_reference_edge.assert_not_awaited()
