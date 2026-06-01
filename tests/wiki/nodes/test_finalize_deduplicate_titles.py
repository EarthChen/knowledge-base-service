"""Tests for F3: global title uniqueness (_deduplicate_titles)."""

from __future__ import annotations

from wiki.nodes.finalize import (
    _deduplicate_titles,
    _detect_near_duplicate_titles,
    _extract_domain_from_path,
)


def test_deduplicate_titles_no_duplicates() -> None:
    pages = [
        {"title": "用户管理", "path": "/__domains__/user-mgmt/_overview", "business_domain": "user-mgmt"},
        {"title": "订单处理", "path": "/__domains__/order/topics/order-flow/_topic", "business_domain": "order"},
    ]
    result = _deduplicate_titles(list(pages))
    assert result[0]["title"] == "用户管理"
    assert result[1]["title"] == "订单处理"


def test_deduplicate_titles_appends_domain() -> None:
    pages = [
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/intimacy/_topic",
            "business_domain": "friend-relation",
        },
        {
            "title": "挚友关系管理",
            "path": "/__domains__/family-relation/topics/intimacy/_topic",
            "business_domain": "family-relation",
        },
    ]
    result = _deduplicate_titles(list(pages))
    titles = {p["title"] for p in result}
    assert "挚友关系管理（friend-relation）" in titles
    assert "挚友关系管理（family-relation）" in titles


def test_deduplicate_titles_truncates_long() -> None:
    long_title = "这是一个非常非常非常非常非常非常非常非常非常非常长的标题用于测试截断"
    pages = [
        {"title": long_title, "path": "/__domains__/domain-a/_overview", "business_domain": "domain-a"},
        {"title": long_title, "path": "/__domains__/domain-b/_overview", "business_domain": "domain-b"},
    ]
    result = _deduplicate_titles(list(pages))
    for p in result:
        assert len(p["title"]) <= 50
        assert p["title"].endswith("）")


def test_extract_domain_from_path() -> None:
    assert _extract_domain_from_path("/__domains__/billing/_overview") == "billing"
    assert _extract_domain_from_path("/__domains__/billing/topics/foo/_topic") == "billing"
    assert _extract_domain_from_path("wiki/my-biz/user-mgmt/overview") == "user-mgmt"
    assert _extract_domain_from_path("wiki/my-biz/user-mgmt/topics/topic-slug") == "user-mgmt"
    assert _extract_domain_from_path("") == ""
    assert _extract_domain_from_path("/other/path") == ""


def test_deduplicate_titles_uses_path_when_no_business_domain() -> None:
    pages = [
        {"title": "用户资料与状态", "path": "/__domains__/profile/_overview"},
        {"title": "用户资料与状态", "path": "/__domains__/account/topics/status/_topic"},
    ]
    result = _deduplicate_titles(list(pages))
    titles = {p["title"] for p in result}
    assert "用户资料与状态（profile）" in titles
    assert "用户资料与状态（account）" in titles


def test_deduplicate_titles_same_domain_different_page_types() -> None:
    pages = [
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/_overview",
            "business_domain": "friend-relation",
            "page_type": "domain_overview",
        },
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/intimacy/_topic",
            "business_domain": "friend-relation",
            "page_type": "topic",
        },
    ]
    result = _deduplicate_titles(list(pages))
    titles = [p["title"] for p in result]
    assert len(titles) == len(set(titles))
    assert any("概览" in t for t in titles)
    assert any("专题" in t for t in titles)


def test_deduplicate_titles_same_domain_same_type() -> None:
    pages = [
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/intimacy/_topic",
            "business_domain": "friend-relation",
            "page_type": "topic",
        },
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/gift/_topic",
            "business_domain": "friend-relation",
            "page_type": "topic",
        },
    ]
    result = _deduplicate_titles(list(pages))
    titles = [p["title"] for p in result]
    assert len(titles) == len(set(titles))
    assert sum("2" in t or "1" in t for t in titles) >= 1


def test_deduplicate_titles_empty_domain() -> None:
    pages = [
        {"title": "通用说明", "path": "/misc/page-a"},
        {"title": "通用说明", "path": "/misc/page-b"},
    ]
    result = _deduplicate_titles(list(pages))
    titles = [p["title"] for p in result]
    assert len(titles) == len(set(titles))
    assert any("1" in t or "2" in t for t in titles)


def test_deduplicate_titles_guarantees_uniqueness() -> None:
    pages = [
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/a/_topic",
            "business_domain": "friend-relation",
            "page_type": "topic",
        },
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/b/_topic",
            "business_domain": "friend-relation",
            "page_type": "topic",
        },
        {
            "title": "挚友关系管理",
            "path": "/__domains__/family-relation/topics/a/_topic",
            "business_domain": "family-relation",
            "page_type": "topic",
        },
        {"title": "通用说明", "path": "/misc/x"},
        {"title": "通用说明", "path": "/misc/y"},
    ]
    result = _deduplicate_titles(list(pages))
    titles = [p["title"] for p in result]
    assert len(titles) == len(set(titles))


def test_detect_near_duplicate_titles() -> None:
    pages = [
        {
            "title": "用户权限管理",
            "path": "/__domains__/auth/topics/perm/_topic",
            "business_domain": "auth",
        },
        {
            "title": "用户权限管",
            "path": "/__domains__/auth/topics/perm2/_topic",
            "business_domain": "auth",
        },
    ]
    result = _detect_near_duplicate_titles(list(pages))
    titles = [p["title"] for p in result]
    assert titles[0] != titles[1]
