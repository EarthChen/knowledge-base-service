"""Canonical_key–based topic→domain linking in wiki.tree_linker.

Topic pages may use ``wiki/<segment>/...`` paths whose first segment matches one
domain heuristically while the page's ``canonical_key`` (as used in ``[[key]]``
wikilinks in generated markdown) identifies the true owning domain via module
membership. ``WikiTreeLinker`` must prefer exact canonical_key lookup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.dependency_graph import DomainNode
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker


def test_find_domain_by_canonical_key_exact_match():
    linker = WikiTreeLinker(store=None, wiki_store=None, wiki_cfg=None, persistence=None)

    class FakePage:
        def __init__(self, key):
            self.canonical_key = key

    pages = [FakePage("src-auth"), FakePage("src-payment"), FakePage("src-order")]
    result = linker._find_domain_by_canonical_key("src-payment", pages)
    assert result is not None
    assert result.canonical_key == "src-payment"


def test_find_domain_by_canonical_key_no_match_returns_none():
    linker = WikiTreeLinker(store=None, wiki_store=None, wiki_cfg=None, persistence=None)

    class FakePage:
        def __init__(self, key):
            self.canonical_key = key

    pages = [FakePage("src-auth")]
    result = linker._find_domain_by_canonical_key("src-nonexistent", pages)
    assert result is None


def test_find_domain_by_canonical_key_empty_list():
    linker = WikiTreeLinker(store=None, wiki_store=None, wiki_cfg=None, persistence=None)
    result = linker._find_domain_by_canonical_key("anything", [])
    assert result is None


def test_build_canonical_key_maps_first_domain_wins():
    tree = [
        DomainNode(
            name="Alpha",
            modules=["m1"],
            children=[],
        ),
    ]
    pages_by_entity = {
        "m1": {"uid": "wp-m1", "canonical_key": "shard-pay"},
    }
    key_dom, key_page = WikiTreeLinker.build_canonical_key_maps(tree, pages_by_entity)
    assert key_dom["shard-pay"] == "Alpha"
    assert key_page["shard-pay"]["uid"] == "wp-m1"


@pytest.mark.asyncio
async def test_nested_tree_topic_canonical_key_overrides_path_fuzzy_domain() -> None:
    """Path segment matches domain Service; canonical_key matches Authentication module.

    Without canonical_key indexing, the topic would link under ``Service``.
    Exact ``canonical_key`` (the same identifier used in ``[[shard-auth]]``-style
    links in composed markdown) must attach the topic under ``Authentication``.
    """
    business_id = "biz-canonical"
    tb = WikiTreeBuilder()
    auth_section_uid = tb.generate_domain_section_uid(business_id, "Authentication")

    domain_tree = [
        DomainNode(name="Service", description="", modules=[], children=[]),
        DomainNode(
            name="Authentication",
            description="",
            modules=["AuthService"],
            children=[],
        ),
    ]
    pages_by_entity_uid = {
        "AuthService": {
            "uid": "wp:AuthService",
            "canonical_key": "shard-auth",
            "title": "AuthService",
        },
    }

    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    topic_uid = "wp:topic-service-path"
    wiki_store.execute_query = AsyncMock(
        side_effect=[
            MagicMock(data=[]),
            MagicMock(
                data=[
                    {
                        "uid": topic_uid,
                        "path": "wiki/Service/topic-under-wrong-segment",
                        "canonical_key": "shard-auth",
                    },
                ],
            ),
            MagicMock(data=[]),
            MagicMock(data=[]),
        ],
    )

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    await linker.link_pages_to_nested_tree(
        business_id,
        domain_tree,
        pages_by_entity_uid,
        tb,
        language="en",
    )

    topic_edges = [
        c
        for c in wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("child_uid") == topic_uid
        and c.kwargs.get("child_label") == "WikiPage"
    ]
    assert topic_edges, "expected HAS_CHILD from topic page to some section"
    assert all(c.kwargs.get("parent_uid") == auth_section_uid for c in topic_edges), (
        "canonical_key shard-auth must link topic under Authentication, not Service"
    )


@pytest.mark.asyncio
async def test_nested_tree_topic_falls_back_to_fuzzy_when_no_canonical_match() -> None:
    business_id = "biz-fuzzy"
    tb = WikiTreeBuilder()
    svc_section_uid = tb.generate_domain_section_uid(business_id, "Service")

    domain_tree = [
        DomainNode(name="Service", description="", modules=[], children=[]),
    ]
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    topic_uid = "wp:topic-fuzzy"
    wiki_store.execute_query = AsyncMock(
        side_effect=[
            MagicMock(data=[]),
            MagicMock(
                data=[
                    {
                        "uid": topic_uid,
                        "path": "wiki/Service/only-segment",
                        "canonical_key": "",
                    },
                ],
            ),
            MagicMock(data=[]),
            MagicMock(data=[]),
        ],
    )
    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    await linker.link_pages_to_nested_tree(
        business_id,
        domain_tree,
        {},
        tb,
        language="en",
    )

    topic_edges = [
        c
        for c in wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("child_uid") == topic_uid
    ]
    assert topic_edges
    assert all(c.kwargs.get("parent_uid") == svc_section_uid for c in topic_edges)


@pytest.mark.asyncio
async def test_nested_tree_topic_unknown_canonical_key_skips_fuzzy_match() -> None:
    """Non-empty canonical_key with no domain mapping must not fall back to path fuzzy match."""
    business_id = "biz-unknown-ck"
    tb = WikiTreeBuilder()

    domain_tree = [
        DomainNode(name="Service", description="", modules=[], children=[]),
        DomainNode(
            name="Authentication",
            description="",
            modules=["AuthService"],
            children=[],
        ),
    ]
    pages_by_entity_uid = {
        "AuthService": {
            "uid": "wp:AuthService",
            "canonical_key": "shard-auth",
            "title": "AuthService",
        },
    }

    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    topic_uid = "wp:topic-unknown-ck"
    wiki_store.execute_query = AsyncMock(
        side_effect=[
            MagicMock(data=[]),
            MagicMock(
                data=[
                    {
                        "uid": topic_uid,
                        "path": "wiki/Service/topic-with-unknown-canonical",
                        "canonical_key": "no-such-key-in-domains",
                    },
                ],
            ),
            MagicMock(data=[]),
            MagicMock(data=[]),
        ],
    )

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    await linker.link_pages_to_nested_tree(
        business_id,
        domain_tree,
        pages_by_entity_uid,
        tb,
        language="en",
    )

    topic_edges = [
        c
        for c in wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("child_uid") == topic_uid
    ]
    assert not topic_edges, (
        "unknown canonical_key must not fuzzy-resolve via path segment Service"
    )
