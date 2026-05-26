"""Tests for wiki tree linker bug fixes.

Bug A: pages_by_entity was empty because get_wiki_pages_for_business
       requires HAS_CHILD traversal which doesn't exist yet
Bug B: canonical_key not returned by queries
Bug C: orphan adoption skipped unconditionally when reassembly enabled
Bug D: path parsing broken for /__domains__/ paths
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.dependency_graph import DomainNode
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker


@pytest.mark.asyncio
async def test_orphan_adoption_runs_when_reassembly_failed() -> None:
    """Bug C: When domain_reassembly_enabled=True but reassembly_succeeded=False,
    orphan adoption should NOT be skipped."""
    wiki_store = MagicMock()
    wiki_store.execute_query = AsyncMock(
        side_effect=[
            # all overview pages query
            MagicMock(data=[
                {"uid": "wp:orphan1", "title": "Orphan Domain", "module_names": ["mod1"]},
            ]),
            # linked pages query - empty (orphan is unlinked)
            MagicMock(data=[]),
        ],
    )
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    domain_tree = [
        DomainNode(name="Alpha", modules=["mod1"], children=[]),
    ]
    tb = WikiTreeBuilder()
    section_uid = tb.generate_domain_section_uid("biz", "Alpha")
    domain_path_to_section_uid = {"Alpha": section_uid}

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), MagicMock())

    with patch("wiki.tree_linker.get_settings") as mock_settings:
        mock_settings.return_value.wiki.domain_reassembly_enabled = True
        await linker._adopt_orphan_domain_pages(
            "biz",
            domain_tree,
            domain_path_to_section_uid,
            tb,
            reassembly_succeeded=False,
        )

    has_child_calls = wiki_store.add_has_child_edge.await_args_list
    adopted = [c for c in has_child_calls if c.kwargs.get("child_uid") == "wp:orphan1"]
    assert adopted, "orphan should be adopted when reassembly failed"


@pytest.mark.asyncio
async def test_orphan_adoption_skipped_when_reassembly_succeeded() -> None:
    """Bug C: When reassembly_succeeded=True, orphan adoption should be skipped."""
    wiki_store = MagicMock()
    wiki_store.execute_query = AsyncMock()

    domain_tree = [DomainNode(name="Alpha", modules=["mod1"], children=[])]
    tb = WikiTreeBuilder()
    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), MagicMock())

    with patch("wiki.tree_linker.get_settings") as mock_settings:
        mock_settings.return_value.wiki.domain_reassembly_enabled = True
        await linker._adopt_orphan_domain_pages(
            "biz",
            domain_tree,
            {"Alpha": "sec-uid"},
            tb,
            reassembly_succeeded=True,
        )

    wiki_store.execute_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_topic_path_parsing_handles_domains_prefix() -> None:
    """Bug D: Topic pages with /__domains__/ path prefix should be parsed correctly."""
    business_id = "biz-path"
    tb = WikiTreeBuilder()

    domain_tree = [
        DomainNode(name="payment-service", description="", modules=["PaySvc"], children=[]),
    ]
    pages_by_entity_uid = {
        "PaySvc": {
            "uid": "wp:PaySvc",
            "canonical_key": "",
            "title": "PaySvc",
        },
    }

    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    topic_uid = "wp:topic-domains-path"
    wiki_store.execute_query = AsyncMock(
        side_effect=[
            MagicMock(data=[]),  # agent overview check
            MagicMock(
                data=[
                    {
                        "uid": topic_uid,
                        "path": "/__domains__/payment-service/_topic",
                        "canonical_key": "",
                    },
                ],
            ),  # topic pages
            MagicMock(data=[]),  # orphan all query
            MagicMock(data=[]),  # orphan linked query
        ],
    )

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)

    with patch("wiki.tree_linker.get_settings") as mock_settings:
        mock_settings.return_value.wiki.domain_reassembly_enabled = False
        await linker.link_pages_to_nested_tree(
            business_id,
            domain_tree,
            pages_by_entity_uid,
            tb,
            language="en",
        )

    section_uid = tb.generate_domain_section_uid(business_id, "payment-service")
    topic_edges = [
        c
        for c in wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("child_uid") == topic_uid and c.kwargs.get("child_label") == "WikiPage"
    ]
    assert topic_edges, "topic page with /__domains__/ path should be linked"
    assert any(c.kwargs.get("parent_uid") == section_uid for c in topic_edges), (
        "topic should be linked under payment-service section"
    )
