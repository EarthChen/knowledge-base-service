"""Tests for pinyin-based topic slug fallback in path_conventions."""
from __future__ import annotations

from wiki.path_conventions import _pinyin_slug, domain_topic_path


class TestPinyinSlug:
    def test_chinese_title_transliterates(self) -> None:
        slug = _pinyin_slug("家族任务与互动运营")
        assert slug
        assert slug == "jia-zu-ren-wu-yu-hu-dong-yun-ying"

    def test_mixed_chinese_ascii(self) -> None:
        slug = _pinyin_slug("用户VIP权益服务")
        assert slug
        assert "vip" in slug
        assert slug.startswith("yong-hu")

    def test_ascii_only_returns_empty(self) -> None:
        assert _pinyin_slug("abc") == ""

    def test_domain_topic_path_uses_pinyin_not_hash(self) -> None:
        path = domain_topic_path("family-events", "家族任务系统")
        assert "topic-" not in path.split("/")[-2]
        assert "jia" in path or "ren-wu" in path

    def test_domain_topic_path_ascii_section_unchanged(self) -> None:
        path = domain_topic_path("family-events", "task-system")
        assert path == "/__domains__/family-events/task-system/_topic"
