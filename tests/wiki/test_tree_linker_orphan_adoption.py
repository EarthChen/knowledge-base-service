"""Tests for orphan domain page adoption in WikiTreeLinker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.dependency_graph import DomainNode
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker


@pytest.fixture(autouse=True)
def _disable_reassembly():
    """Disable domain_reassembly so orphan adoption runs in these tests."""
    with patch("wiki.tree_linker.get_settings") as mock_gs:
        mock_gs.return_value.wiki.domain_reassembly_enabled = False
        yield


def _make_linker(wiki_store: MagicMock) -> WikiTreeLinker:
    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()
    return WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)


def _query_result(data: list[dict]) -> MagicMock:
    return MagicMock(data=data)


@pytest.mark.asyncio
async def test_orphan_adopted_via_module_overlap() -> None:
    """Orphan page sharing SOURCE_ENTITY modules with a domain node gets adopted."""
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    wiki_store.execute_query = AsyncMock(side_effect=[
        _query_result([]),  # no agent overviews
        _query_result([]),  # no topic pages
        _query_result([     # all domain overviews
            {"uid": "WikiPage:biz:/__domains__/old-slug/_overview",
             "title": "IM消息处理", "module_names": ["ChatService", "MessageHandler"]},
        ]),
        _query_result([]),  # none linked yet → all are orphans
    ])

    domain_tree = [
        DomainNode(
            name="im-chat",
            display_name="即时通讯",
            modules=["ChatService", "MessageHandler", "SessionManager"],
        ),
        DomainNode(name="payment", display_name="支付", modules=["PayService"]),
    ]

    linker = _make_linker(wiki_store)
    await linker.link_pages_to_nested_tree(
        "biz", domain_tree, {}, WikiTreeBuilder(), language="zh",
    )

    adoption_calls = [
        c for c in wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("child_uid") == "WikiPage:biz:/__domains__/old-slug/_overview"
        and c.kwargs.get("view_type") == "business_domain"
    ]
    assert len(adoption_calls) == 1
    assert "im-chat" in adoption_calls[0].kwargs["parent_uid"]


@pytest.mark.asyncio
async def test_orphan_adopted_via_cjk_title_similarity() -> None:
    """Orphan page with no modules matched but similar CJK title gets adopted."""
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    wiki_store.execute_query = AsyncMock(side_effect=[
        _query_result([]),  # no agent overviews
        _query_result([]),  # no topic pages
        _query_result([
            {"uid": "WikiPage:biz:/__domains__/old-family/_overview",
             "title": "家族核心管理与任务", "module_names": []},
        ]),
        _query_result([]),  # none linked
    ])

    domain_tree = [
        DomainNode(name="clan-mgmt", display_name="家族核心管理", modules=["ClanCore"]),
        DomainNode(name="social", display_name="社交互动", modules=["SocialFeed"]),
    ]

    linker = _make_linker(wiki_store)
    await linker.link_pages_to_nested_tree(
        "biz", domain_tree, {}, WikiTreeBuilder(), language="zh",
    )

    adoption_calls = [
        c for c in wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("child_uid") == "WikiPage:biz:/__domains__/old-family/_overview"
        and c.kwargs.get("view_type") == "business_domain"
    ]
    assert len(adoption_calls) == 1
    assert "clan-mgmt" in adoption_calls[0].kwargs["parent_uid"]


@pytest.mark.asyncio
async def test_orphan_no_match_goes_to_unassigned() -> None:
    """Orphan page with no module overlap and dissimilar title goes to __unassigned__ section."""
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    wiki_store.execute_query = AsyncMock(side_effect=[
        _query_result([]),  # no agent overviews
        _query_result([]),  # no topic pages
        _query_result([
            {"uid": "WikiPage:biz:/__domains__/random/_overview",
             "title": "完全无关的页面", "module_names": ["UnknownModule"]},
        ]),
        _query_result([]),  # none linked
    ])

    domain_tree = [
        DomainNode(name="payment", display_name="支付系统", modules=["PayService"]),
    ]

    tb = WikiTreeBuilder()
    linker = _make_linker(wiki_store)
    await linker.link_pages_to_nested_tree(
        "biz", domain_tree, {}, tb, language="zh",
    )

    orphan_uid = "WikiPage:biz:/__domains__/random/_overview"
    unassigned_uid = tb.generate_domain_section_uid("biz", "__unassigned__")

    # Orphan should be linked under __unassigned__ section
    unassigned_calls = [
        c for c in wiki_store.add_has_child_edge.await_args_list
        if c.kwargs.get("child_uid") == orphan_uid
        and c.kwargs.get("parent_uid") == unassigned_uid
    ]
    assert len(unassigned_calls) == 1

    # __unassigned__ section should be created
    section_calls = [
        c for c in wiki_store.upsert_wiki_section.await_args_list
        if c.kwargs.get("uid") == unassigned_uid
    ]
    assert len(section_calls) == 1
    assert section_calls[0].kwargs["title"] == "待分配页面"


@pytest.mark.asyncio
async def test_no_orphans_early_return() -> None:
    """When all domain overview pages are already linked, adoption is skipped."""
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    linked_uid = "WikiPage:biz:/__domains__/im-chat/_overview"
    wiki_store.execute_query = AsyncMock(side_effect=[
        _query_result([]),  # no agent overviews
        _query_result([]),  # no topic pages
        _query_result([
            {"uid": linked_uid, "title": "即时通讯", "module_names": ["ChatService"]},
        ]),
        _query_result([
            {"uid": linked_uid},
        ]),
    ])

    domain_tree = [
        DomainNode(name="im-chat", display_name="即时通讯", modules=["ChatService"]),
    ]

    linker = _make_linker(wiki_store)
    await linker.link_pages_to_nested_tree(
        "biz", domain_tree, {}, WikiTreeBuilder(), language="zh",
    )

    for c in wiki_store.add_has_child_edge.await_args_list:
        if c.kwargs.get("child_uid") == linked_uid:
            assert c.kwargs.get("sort_order", 0) < 10000, "Should not be an adoption edge"
