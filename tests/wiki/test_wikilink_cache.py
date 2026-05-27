from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.wikilink_cache import WikiLinkCache


def test_cache_empty_by_default():
    cache = WikiLinkCache()
    assert cache.get_index() == {}
    assert cache.is_loaded is False


def test_cache_register_and_lookup():
    cache = WikiLinkCache()
    cache.register("MyClass", "classes/MyClass.md")
    index = cache.get_index()
    assert "MyClass" in index
    assert "MyClass.md" in index["MyClass"]


def test_cache_get_title_for_path():
    cache = WikiLinkCache()
    cache.register("MyClass", "classes/MyClass.md")
    assert cache.get_title_for_path("classes/MyClass.md") == "MyClass"
    assert cache.get_title_for_path("nonexistent.md") is None


def test_cache_register_strips_whitespace():
    cache = WikiLinkCache()
    cache.register("  MyClass  ", "classes/MyClass.md")
    index = cache.get_index()
    assert "MyClass" in index


def test_cache_register_composite_domain_title_key():
    cache = WikiLinkCache()
    cache.register("Invoicing", "/__domains__/billing/topics/Invoicing.md", business_domain="billing")
    index = cache.get_index()
    assert "Invoicing" in index
    assert "billing/invoicing" in index
    assert index["billing/invoicing"] == index["Invoicing"]


def test_cache_register_without_business_domain_has_no_composite():
    cache = WikiLinkCache()
    cache.register("MyClass", "classes/MyClass.md")
    index = cache.get_index()
    assert "MyClass" in index
    assert not any("/" in k for k in index)


@pytest.mark.asyncio
async def test_cache_warm_up_loads_composite_keys_from_business_domain() -> None:
    wiki_store = MagicMock()
    wiki_store.list_wiki_pages_all = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "title": "Invoicing",
                    "path": "/__domains__/billing/topics/Invoicing.md",
                    "page_type": "topic",
                    "business_domain": "billing",
                },
            ],
        ),
    )
    cache = WikiLinkCache()
    count = await cache.warm_up(wiki_store, "myrepo")
    assert count == 1
    assert cache.is_loaded is True
    index = cache.get_index()
    assert "Invoicing" in index
    assert "billing/invoicing" in index
    assert index["billing/invoicing"] == index["Invoicing"]
