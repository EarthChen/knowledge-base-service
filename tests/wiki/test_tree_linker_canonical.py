import pytest
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
