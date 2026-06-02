"""Tests: finalize must not expose domain slugs or page_type labels in user-visible titles."""

from __future__ import annotations

from wiki.nodes.finalize import (
    _deduplicate_exact_titles,
    _deduplicate_titles,
    _detect_near_duplicate_titles,
    _disambiguation_parts,
    _sanitize_title_suffix,
    _title_has_exposed_slug,
)


def test_disambiguation_uses_numeric_not_slug() -> None:
    pages = [
        {
            "title": "评分弹窗核心服务",
            "path": "/__domains__/app-store-rating-popup/topics/rating/_topic",
            "business_domain": "app-store-rating-popup",
            "page_type": "topic",
            "content": "# Title\n\nBody.",
        },
        {
            "title": "评分弹窗核心服务",
            "path": "/__domains__/app-store-rating-popup/_overview",
            "business_domain": "app-store-rating-popup",
            "page_type": "domain_overview",
            "content": "# Title\n\nBody.",
        },
    ]
    result = _deduplicate_exact_titles(list(pages))
    titles = {p["title"] for p in result}
    assert "app-store-rating-popup" not in " ".join(titles)
    assert "专题" not in " ".join(titles)
    assert "概览" not in " ".join(titles)
    assert any("（1）" in t or "（2）" in t for t in titles)


def test_near_duplicate_uses_module_name() -> None:
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
    second_title = result[1]["title"]
    assert "auth" not in second_title
    assert "app-store-rating-popup" not in second_title
    assert second_title != result[0]["title"]


def test_sanitize_removes_kebab_slug() -> None:
    assert _sanitize_title_suffix("app-store-rating-popup") == ""
    assert _sanitize_title_suffix("app-store-rating-popup·专题·1") == "1"
    assert "app-store" not in _sanitize_title_suffix("foo·app-store-rating-popup·bar")


def test_sanitize_keeps_chinese() -> None:
    assert _sanitize_title_suffix("排名计算") == "排名计算"
    assert _sanitize_title_suffix("排名计算·1") == "排名计算·1"


def test_final_title_no_slug_pattern() -> None:
    pages = [
        {
            "title": "评分弹窗核心服务",
            "path": "/__domains__/app-store-rating-popup/topics/rating/_topic",
            "business_domain": "app-store-rating-popup",
            "page_type": "topic",
        },
        {
            "title": "评分弹窗核心服务",
            "path": "/__domains__/app-store-rating-popup/_overview",
            "business_domain": "app-store-rating-popup",
            "page_type": "domain_overview",
        },
    ]
    result = _deduplicate_titles(list(pages))
    for page in result:
        title = page["title"]
        assert not _title_has_exposed_slug(title), f"title still contains kebab slug: {title!r}"


def test_h2_theme_preferred_over_numeric() -> None:
    pages = [
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/intimacy/_topic",
            "business_domain": "friend-relation",
            "content": "# Title\n\n## 亲密度计算\n\nDetails.",
        },
        {
            "title": "挚友关系管理",
            "path": "/__domains__/friend-relation/topics/gift/_topic",
            "business_domain": "friend-relation",
            "content": "# Title\n\n## 礼物赠送\n\nDetails.",
        },
    ]
    result = _deduplicate_exact_titles(list(pages))
    titles = {p["title"] for p in result}
    assert any("亲密度计算" in t for t in titles)
    assert any("礼物赠送" in t for t in titles)
    assert "friend-relation" not in " ".join(titles)


def test_disambiguation_parts_level1_is_numeric_only() -> None:
    page = {
        "path": "/__domains__/app-store-rating-popup/topics/rating/_topic",
        "business_domain": "app-store-rating-popup",
        "page_type": "topic",
    }
    parts = _disambiguation_parts(page, level=1, seq=2)
    assert parts == ("2",)
    assert "app-store-rating-popup" not in parts
