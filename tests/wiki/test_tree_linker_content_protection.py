"""Verify TreeLinker preserves rich existing overview content over static templates."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.dependency_graph import DomainNode
from wiki.path_conventions import domain_overview_path
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker

SHORT_CONTENT = "# Title\n\nShort."
RICH_CONTENT = "# Family Domain\n\n" + "Detailed description. " * 50


class TestTreeLinkerContentProtection:
    """Verify that TreeLinker doesn't overwrite rich existing content with static templates."""

    def test_short_content_below_threshold(self) -> None:
        """Content shorter than threshold should be replaced by generated overview."""
        assert len(SHORT_CONTENT) < 500

    def test_rich_content_above_threshold(self) -> None:
        """Content longer than 500 chars qualifies for preservation."""
        assert len(RICH_CONTENT) > 500


@pytest.mark.asyncio
async def test_rich_existing_overview_content_preserved() -> None:
    """When pages_by_entity_uid has rich overview content, persist must keep it."""
    business_id = "biz-rich"
    tb = WikiTreeBuilder()
    domain = DomainNode(name="FamilyDomain", modules=["ModA"], children=[], description="")
    overview_path = domain_overview_path(domain.name)
    overview_uid = f"WikiPage:{business_id}:{overview_path}"

    pages_by_entity_uid = {
        "ModA": {"uid": "wp:mod-a", "title": "ModA", "content": ""},
        overview_uid: {
            "uid": overview_uid,
            "title": "FamilyDomain",
            "path": overview_path,
            "content": RICH_CONTENT,
            "page_type": "domain_overview",
        },
    }

    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    wiki_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    await linker.link_pages_to_nested_tree(
        business_id,
        [domain],
        pages_by_entity_uid,
        tb,
        language="en",
    )

    persistence.persist_pages_to_graph.assert_awaited_once()
    pages = persistence.persist_pages_to_graph.call_args[0][1]
    overview_pages = [p for p in pages if p.path.endswith("/_overview")]
    assert len(overview_pages) == 1
    assert overview_pages[0].content == RICH_CONTENT


@pytest.mark.asyncio
async def test_short_existing_overview_content_overwritten() -> None:
    """Short existing overview content should be replaced by generated overview."""
    business_id = "biz-short"
    tb = WikiTreeBuilder()
    domain = DomainNode(name="FamilyDomain", modules=["ModA"], children=[], description="Domain desc")
    overview_path = domain_overview_path(domain.name)
    overview_uid = f"WikiPage:{business_id}:{overview_path}"

    pages_by_entity_uid = {
        "ModA": {"uid": "wp:mod-a", "title": "ModA", "content": ""},
        overview_uid: {
            "uid": overview_uid,
            "title": "FamilyDomain",
            "path": overview_path,
            "content": SHORT_CONTENT,
            "page_type": "domain_overview",
        },
    }

    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    wiki_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    await linker.link_pages_to_nested_tree(
        business_id,
        [domain],
        pages_by_entity_uid,
        tb,
        language="en",
    )

    persistence.persist_pages_to_graph.assert_awaited_once()
    pages = persistence.persist_pages_to_graph.call_args[0][1]
    overview_pages = [p for p in pages if p.path.endswith("/_overview")]
    assert len(overview_pages) == 1
    assert overview_pages[0].content != SHORT_CONTENT
    assert "# FamilyDomain" in overview_pages[0].content
