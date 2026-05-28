"""Tests for F4: tree_linker shell domain gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.dependency_graph import DomainNode
from wiki.models import EnrichmentLevel, PageType, WikiPage, WikiPageMetadata
from wiki.path_conventions import domain_overview_path
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker, _filter_overview_pages_for_persist, _warn_duplicate_titles_before_persist

RICH_OVERVIEW = "# 家庭域\n\n## 概述\n\n" + "这是详细的业务描述内容，用于覆盖质量阈值。" * 20
ALLOWED_OVERVIEW = "## 概述\n\n" + "本模块提供核心业务功能，实现了完整的数据处理流程。" * 10


def _make_wiki_page(*, path: str, content: str, title: str = "Test") -> WikiPage:
    return WikiPage(
        path=path,
        title=title,
        page_type=PageType.DOMAIN_OVERVIEW,
        content=content,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(
            node_count=1,
            edge_count=0,
            generation_mode="business",
            enrichment_level=EnrichmentLevel.BASE,
        ),
    )


def _make_linker() -> tuple[WikiTreeLinker, MagicMock]:
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()
    wiki_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, MagicMock(), persistence)
    return linker, persistence


def test_warn_duplicate_titles_before_persist() -> None:
    pages = [
        _make_wiki_page(path="/__domains__/a/_overview", content=ALLOWED_OVERVIEW, title="重复标题"),
        _make_wiki_page(path="/__domains__/b/_overview", content=ALLOWED_OVERVIEW, title="重复标题"),
    ]
    with patch("wiki.tree_linker.log.warning") as mock_warning:
        _warn_duplicate_titles_before_persist(pages, repository="biz-1")
    dup_calls = [c for c in mock_warning.call_args_list if c[0][0] == "duplicate_wiki_page_titles_before_persist"]
    assert len(dup_calls) == 1
    assert dup_calls[0][1]["title"] == "重复标题"
    assert len(dup_calls[0][1]["paths"]) == 2


def test_warn_duplicate_titles_skips_unique() -> None:
    pages = [
        _make_wiki_page(path="/__domains__/a/_overview", content=ALLOWED_OVERVIEW, title="标题A"),
        _make_wiki_page(path="/__domains__/b/_overview", content=ALLOWED_OVERVIEW, title="标题B"),
    ]
    _warn_duplicate_titles_before_persist(pages, repository="biz-1")


def test_overview_passes_sanitize_and_exceeds_threshold() -> None:
    """Content that survives sanitize and meets the min length is kept."""
    page = _make_wiki_page(path="/__domains__/good/_overview", content=f"# 标题\n\n{ALLOWED_OVERVIEW}")

    filtered = _filter_overview_pages_for_persist([page])

    assert len(filtered) == 1
    assert len(filtered[0].content.strip()) >= 200
    assert filtered[0].content.startswith("## 概述")


def test_overview_filtered_when_sanitize_short() -> None:
    """Shell content below 200 chars after sanitize is dropped."""
    shell = "# Tiny\n\n## Key Modules\n\n- **ModA**\n"
    page = _make_wiki_page(path="/__domains__/tiny/_overview", content=shell)

    filtered = _filter_overview_pages_for_persist([page])

    assert filtered == []


def test_h1_title_stripped_before_sanitize() -> None:
    """Leading H1 is removed before sanitize and length check."""
    page = _make_wiki_page(path="/__domains__/strip/_overview", content=f"# 请移除此标题\n\n{ALLOWED_OVERVIEW}")

    filtered = _filter_overview_pages_for_persist([page])

    assert len(filtered) == 1
    assert not filtered[0].content.lstrip().startswith("# 请移除此标题")
    assert filtered[0].content.startswith("## 概述")


@pytest.mark.asyncio
async def test_mixed_overview_pages_only_good_ones_persisted() -> None:
    """Integration: rich overview persists while shell overview is filtered out."""
    business_id = "biz-mixed"
    tb = WikiTreeBuilder()
    rich_path = domain_overview_path("RichDomain")
    rich_uid = f"WikiPage:{business_id}:{rich_path}"

    tiny_domain = DomainNode(name="TinyDomain", modules=["ModTiny"], children=[], description="")
    rich_domain = DomainNode(name="RichDomain", modules=["ModRich"], children=[], description="")

    _module_content = "## 概述\n\n" + "本模块实现核心业务逻辑，提供完整的数据处理流水线支持，包含事件驱动和异步通信机制。" * 15
    pages_by_entity_uid = {
        "ModTiny": {"uid": "wp:mod-tiny", "title": "ModTiny", "content": ""},
        "ModRich": {"uid": "wp:mod-rich", "title": "ModRich", "content": _module_content},
        rich_uid: {
            "uid": rich_uid,
            "title": "RichDomain",
            "path": rich_path,
            "content": RICH_OVERVIEW,
            "page_type": "domain_overview",
        },
    }

    linker, persistence = _make_linker()
    await linker.link_pages_to_nested_tree(
        business_id,
        [tiny_domain, rich_domain],
        pages_by_entity_uid,
        tb,
        language="zh",
    )

    persistence.persist_pages_to_graph.assert_awaited_once()
    persisted_pages = persistence.persist_pages_to_graph.call_args[0][1]
    assert len(persisted_pages) == 1
    assert persisted_pages[0].path == rich_path
    assert len(persisted_pages[0].content.strip()) >= 200
    assert not persisted_pages[0].content.lstrip().startswith("# ")


@pytest.mark.asyncio
async def test_shell_only_domain_not_persisted() -> None:
    """Integration: generated shell overview below threshold skips persist entirely."""
    business_id = "biz-shell"
    tb = WikiTreeBuilder()
    domain = DomainNode(name="ShellDomain", modules=["ModA"], children=[], description="")

    pages_by_entity_uid = {
        "ModA": {"uid": "wp:mod-a", "title": "ModA", "content": ""},
    }

    linker, persistence = _make_linker()
    await linker.link_pages_to_nested_tree(
        business_id,
        [domain],
        pages_by_entity_uid,
        tb,
        language="zh",
    )

    persistence.persist_pages_to_graph.assert_not_awaited()
