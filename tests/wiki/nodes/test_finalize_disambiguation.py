"""Tests for disambiguation suffix stripping."""
from __future__ import annotations


def test_strips_suffix_when_base_title_unique():
    from wiki.nodes.finalize import _strip_disambiguation_suffixes

    pages = [
        {"title": "关系管理（user-wealth-charm-level）", "path": "p1", "business_domain": "relation"},
        {"title": "家族核心运营", "path": "p2", "page_type": "domain_overview"},
    ]
    result = _strip_disambiguation_suffixes(pages)
    assert result[0]["title"] == "关系管理"
    assert result[1]["title"] == "家族核心运营"


def test_keeps_suffix_when_still_duplicate():
    from wiki.nodes.finalize import _strip_disambiguation_suffixes

    pages = [
        {"title": "用户权益（domain-a）", "business_domain": "domain-a", "path": "p1"},
        {"title": "用户权益（domain-b）", "business_domain": "domain-b", "path": "p2"},
    ]
    result = _strip_disambiguation_suffixes(pages)
    # Both have same base "用户权益" — should keep suffixes
    assert "（" in result[0]["title"] or "（" in result[1]["title"]


def test_keeps_suffix_when_base_conflicts_with_existing():
    from wiki.nodes.finalize import _strip_disambiguation_suffixes

    pages = [
        {"title": "用户权益（domain-a）", "path": "p1"},
        {"title": "用户权益", "path": "p2"},
    ]
    result = _strip_disambiguation_suffixes(pages)
    # Can't strip because "用户权益" already exists as another page's title
    assert result[0]["title"] == "用户权益（domain-a）"


def test_no_change_for_non_disambig_titles():
    from wiki.nodes.finalize import _strip_disambiguation_suffixes

    pages = [
        {"title": "普通标题", "path": "p1"},
        {"title": "Another Title", "path": "p2"},
    ]
    result = _strip_disambiguation_suffixes(pages)
    assert result == pages


def test_handles_empty_list():
    from wiki.nodes.finalize import _strip_disambiguation_suffixes

    assert _strip_disambiguation_suffixes([]) == []
