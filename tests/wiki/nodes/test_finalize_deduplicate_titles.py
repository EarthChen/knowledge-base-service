"""Tests for F3: global title uniqueness (_deduplicate_titles)."""

from __future__ import annotations

from wiki.nodes.finalize import (
    _deduplicate_titles,
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
