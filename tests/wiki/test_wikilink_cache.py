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
