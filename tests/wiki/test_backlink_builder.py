import pytest
from unittest.mock import AsyncMock

from wiki.backlink_builder import BacklinkBuilder
from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.wikilink_cache import WikiLinkCache


@pytest.fixture
def sample_pages():
    def _make_page(path, title, uid):
        page = WikiPage(
            path=path,
            title=title,
            page_type=PageType.CLASS_DETAIL,
            content=f"# {title}\n\nSome content.",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(1, 1),
        )
        page._source_entity_uid = uid
        return page

    return [
        _make_page("classes/Foo.md", "Foo", "uid:Class:Foo"),
        _make_page("classes/Bar.md", "Bar", "uid:Class:Bar"),
    ]


@pytest.fixture
def cache_with_pages(sample_pages):
    cache = WikiLinkCache()
    for p in sample_pages:
        cache.register(p.title, p.path)
    return cache


@pytest.mark.asyncio
async def test_build_backlinks_appends_section(sample_pages, cache_with_pages):
    graph = AsyncMock()
    graph.find_all_referrers_batch = AsyncMock(
        return_value={"uid:Class:Foo": ["uid:Class:Bar"]},
    )
    builder = BacklinkBuilder()
    await builder.build_backlinks(sample_pages, graph, cache_with_pages, "test-repo")
    foo_page = sample_pages[0]
    assert "## Referenced by" in foo_page.content
    assert "Bar" in foo_page.content


@pytest.mark.asyncio
async def test_build_backlinks_no_referrers(sample_pages, cache_with_pages):
    graph = AsyncMock()
    graph.find_all_referrers_batch = AsyncMock(return_value={})
    builder = BacklinkBuilder()
    await builder.build_backlinks(sample_pages, graph, cache_with_pages, "test-repo")
    for page in sample_pages:
        assert "## Referenced by" not in page.content


@pytest.mark.asyncio
async def test_build_backlinks_bidirectional(sample_pages, cache_with_pages):
    graph = AsyncMock()
    graph.find_all_referrers_batch = AsyncMock(
        return_value={
            "uid:Class:Foo": ["uid:Class:Bar"],
            "uid:Class:Bar": ["uid:Class:Foo"],
        },
    )
    builder = BacklinkBuilder()
    await builder.build_backlinks(sample_pages, graph, cache_with_pages, "test-repo")
    assert "## Referenced by" in sample_pages[0].content
    assert "## Referenced by" in sample_pages[1].content
    assert "Bar" in sample_pages[0].content
    assert "Foo" in sample_pages[1].content


@pytest.mark.asyncio
async def test_build_backlinks_deduplicates(sample_pages, cache_with_pages):
    graph = AsyncMock()
    graph.find_all_referrers_batch = AsyncMock(
        return_value={"uid:Class:Foo": ["uid:Class:Bar", "uid:Class:Bar"]},
    )
    builder = BacklinkBuilder()
    await builder.build_backlinks(sample_pages, graph, cache_with_pages, "test-repo")
    foo_content = sample_pages[0].content
    assert foo_content.count("[[Bar]]") == 1
