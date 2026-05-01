"""Unit tests for wiki.tree_linker.WikiTreeLinker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.dependency_graph import DomainNode
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker


@pytest.mark.asyncio
async def test_get_domain_tree_returns_empty_when_no_store() -> None:
    linker = WikiTreeLinker(None, MagicMock(), MagicMock(), MagicMock())
    assert await linker.get_domain_tree("biz") == {"tree": [], "review_status": {}}


@pytest.mark.asyncio
async def test_get_topic_tree_returns_empty_when_no_store() -> None:
    linker = WikiTreeLinker(None, MagicMock(), MagicMock(), MagicMock())
    assert await linker.get_topic_tree("biz") == {"tree": []}


@pytest.mark.asyncio
async def test_get_domain_edges_returns_empty_when_no_store() -> None:
    linker = WikiTreeLinker(None, MagicMock(), MagicMock(), MagicMock())
    assert await linker.get_domain_edges("biz") == {"edges": []}


@pytest.mark.asyncio
async def test_get_domain_tree_delegates_to_wiki_store() -> None:
    mock_store = MagicMock()
    snapshot = {"tree": [{"name": "root"}], "review_status": {"ok": True}}
    with patch("wiki.tree_linker.WikiStore") as WS:
        WS.return_value.get_pipeline_domain_tree_snapshot = AsyncMock(return_value=snapshot)
        linker = WikiTreeLinker(mock_store, None, MagicMock(), MagicMock())
        out = await linker.get_domain_tree("b1")
    assert out is snapshot
    WS.return_value.get_pipeline_domain_tree_snapshot.assert_awaited_once_with("b1")


@pytest.mark.asyncio
async def test_link_pages_to_tree_no_wiki_store_returns_immediately() -> None:
    linker = WikiTreeLinker(MagicMock(), None, MagicMock(), MagicMock())
    await linker.link_pages_to_tree("biz", {"D": []}, ["r1"], WikiTreeBuilder())


@pytest.mark.asyncio
async def test_link_pages_to_tree_empty_repo_names_no_queries() -> None:
    wiki_store = MagicMock()
    wiki_store.execute_query = AsyncMock()
    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), MagicMock())
    await linker.link_pages_to_tree("biz", {"D": [("r1", "m")]}, [], WikiTreeBuilder())
    wiki_store.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_link_pages_to_tree_skips_rows_without_uid() -> None:
    wiki_store = MagicMock()
    wiki_store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {"uid": "", "title": "x", "path": "/", "page_type": "t", "repository": "r1", "entity_uid": ""},
            ]
        )
    )
    wiki_store.add_has_child_edge = AsyncMock()
    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), MagicMock())
    await linker.link_pages_to_tree("biz", {}, ["r1"], WikiTreeBuilder())
    wiki_store.add_has_child_edge.assert_not_called()


@pytest.mark.asyncio
async def test_link_pages_to_tree_creates_code_and_domain_edges() -> None:
    wiki_store = MagicMock()
    wiki_store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "uid": "page-1",
                    "title": "Orders",
                    "path": "/p",
                    "page_type": "module_overview",
                    "repository": "svc",
                    "entity_uid": "",
                },
            ]
        )
    )
    wiki_store.add_has_child_edge = AsyncMock()
    wiki_cfg = MagicMock()
    wiki_cfg.business_domain_infrastructure_label = "Infrastructure"
    tb = WikiTreeBuilder()
    domain_mapping = {"Commerce": [("svc", "Orders")]}
    linker = WikiTreeLinker(MagicMock(), wiki_store, wiki_cfg, MagicMock())
    await linker.link_pages_to_tree("biz", domain_mapping, ["svc"], tb)

    wiki_store.execute_query.assert_awaited_once()
    calls = wiki_store.add_has_child_edge.await_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["view_type"] == "code_structure"
    assert calls[0].kwargs["parent_uid"] == tb.generate_repo_section_uid("biz", "svc")
    assert calls[1].kwargs["view_type"] == "business_domain"
    assert calls[1].kwargs["parent_uid"] == tb.generate_domain_section_uid("biz", "Commerce")


@pytest.mark.asyncio
async def test_link_pages_to_tree_skip_business_domain_only_code_edges() -> None:
    wiki_store = MagicMock()
    wiki_store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "uid": "p1",
                    "title": "M",
                    "path": "/",
                    "page_type": "module_overview",
                    "repository": "r1",
                    "entity_uid": "",
                },
            ]
        )
    )
    wiki_store.add_has_child_edge = AsyncMock()
    tb = WikiTreeBuilder()
    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), MagicMock())
    await linker.link_pages_to_tree(
        "biz",
        {"D": [("r1", "M")]},
        ["r1"],
        tb,
        skip_business_domain=True,
    )
    assert wiki_store.add_has_child_edge.await_count == 1
    assert wiki_store.add_has_child_edge.await_args.kwargs["view_type"] == "code_structure"


@pytest.mark.asyncio
async def test_link_pages_to_nested_tree_no_wiki_store() -> None:
    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()
    linker = WikiTreeLinker(MagicMock(), None, MagicMock(), persistence)
    await linker.link_pages_to_nested_tree(
        "biz",
        [DomainNode(name="Empty")],
        {},
        WikiTreeBuilder(),
    )
    persistence.persist_pages_to_graph.assert_not_called()


@pytest.mark.asyncio
async def test_link_pages_to_nested_tree_ensures_root_for_empty_domain_list() -> None:
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()
    tb = WikiTreeBuilder()
    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    await linker.link_pages_to_nested_tree("biz", [], {}, tb, language="en")

    wiki_store.upsert_wiki_section.assert_awaited()
    root_call = wiki_store.upsert_wiki_section.await_args_list[0]
    assert root_call.kwargs["title"] == "__root__"
    space_child = wiki_store.add_has_child_edge.await_args_list[0]
    assert space_child.kwargs["parent_uid"] == tb.generate_space_uid("biz")
    assert space_child.kwargs["child_uid"] == tb.generate_domain_section_uid("biz", "__root__")


def test_count_domain_modules_nested() -> None:
    tree = DomainNode(
        name="a",
        modules=["m1", "m2"],
        children=[DomainNode(name="b", modules=["m3"], children=[])],
    )
    assert WikiTreeLinker.count_domain_modules(tree) == 3


def test_count_domain_modules_empty_children() -> None:
    assert WikiTreeLinker.count_domain_modules(DomainNode(name="solo")) == 0
