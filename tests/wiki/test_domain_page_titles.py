"""Tests for domain wiki page title and heading display names."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.content_context_builder import EnrichedDomainContext
from wiki.dependency_graph import DomainNode
from wiki.domain_overview_composer import (
    _structural_markdown,
    _structural_markdown_from_enriched_context,
)
from wiki.models import PageType
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker


def test_structural_markdown_uses_display_name() -> None:
    """Structural markdown heading should use display name, not slug."""
    context = EnrichedDomainContext(
        domain_name="user-profile",
        parent_domain="root",
        display_name="用户信息与档案域",
    )
    md = _structural_markdown_from_enriched_context(context, "zh")
    assert md.startswith("# 业务域：用户信息与档案域")
    assert "user-profile" not in md.split("\n", 1)[0]

    md_en = _structural_markdown_from_enriched_context(context, "en")
    assert md_en.startswith("# Domain: 用户信息与档案域")

    md_legacy = _structural_markdown(
        "user-profile",
        {},
        "zh",
        display_name="用户信息与档案域",
    )
    assert md_legacy.startswith("# 业务域：用户信息与档案域")


@pytest.mark.asyncio
async def test_compose_page_title_uses_display_name() -> None:
    """Agent-driven compose path should set page title to display name."""
    from wiki.pipeline_nodes import _compose_single_leaf_domain

    mock_llm = AsyncMock()
    mock_graph = AsyncMock()
    mock_wiki = AsyncMock()

    leaf = {
        "name": "user-profile",
        "display_name": "用户信息与档案域",
        "modules": ["UserService"],
        "parent": "root",
    }
    module_index = {
        "UserService": [
            {
                "uid": "Module::UserService:0",
                "properties": {"name": "UserService", "business_summary": "users"},
                "_repo": "repo1",
            }
        ]
    }
    entity_roles = {"Module::UserService:0": "has_business_logic"}

    long_content = "# 用户信息与档案域\n\n" + ("详细内容。" * 50)

    with (
        patch.dict(os.environ, {"WIKI__AGENT_DRIVEN_GENERATION": "true"}),
        patch(
            "wiki.content_context_builder.ContentContextBuilder.build_context",
            new_callable=AsyncMock,
        ) as mock_build,
        patch("wiki.page_agent.WikiPageAgent.generate", new_callable=AsyncMock) as mock_generate,
    ):
        mock_build.return_value = EnrichedDomainContext(
            domain_name="user-profile",
            parent_domain="root",
            display_name="用户信息与档案域",
        )
        mock_generate.return_value = long_content

        pages, paths = await _compose_single_leaf_domain(
            leaf,
            module_index,
            entity_roles,
            mock_llm,
            8000,
            graph_store=mock_graph,
            wiki_store=mock_wiki,
        )

    assert len(pages) == 1
    assert pages[0]["title"] == "用户信息与档案域"
    assert pages[0]["title"] != "user-profile"
    assert paths == ["wiki/user-profile"]


@pytest.mark.asyncio
async def test_overview_title_fallback_to_slug() -> None:
    """Tree linker overview title falls back to slug when display_name is empty."""
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    wiki_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    domain = DomainNode(
        name="user-profile",
        slug="user-profile",
        display_name="",
        modules=["UserService", "UserDao", "UserController", "UserConfig", "UserMapper"],
        description="User domain",
    )

    with patch("wiki.tree_linker._filter_overview_pages_for_persist", side_effect=lambda pages, **_kw: pages):
        await linker.link_pages_to_nested_tree(
            business_id="biz",
            domain_tree=[domain],
            pages_by_entity_uid={},
            tree_builder=WikiTreeBuilder(),
            language="zh",
        )

    persistence.persist_pages_to_graph.assert_awaited_once()
    pages = persistence.persist_pages_to_graph.call_args[0][1]
    overview_pages = [p for p in pages if getattr(p, "path", "").endswith("/_overview")]
    assert len(overview_pages) == 1
    assert overview_pages[0].title == "user-profile"
    assert overview_pages[0].page_type == PageType.DOMAIN_OVERVIEW
