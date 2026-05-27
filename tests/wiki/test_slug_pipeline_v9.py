"""V9 Batch A — slug pipeline fixes (F1-F4)."""

from __future__ import annotations

from wiki.path_conventions import (
    _sanitize_module_path_slug,
    is_pinyin_slug,
    is_slug_too_generic,
    resolve_slug_collision,
    resolve_topic_slug,
)


class TestSanitizeModulePathSlug:
    def test_sanitize_module_path_slug(self) -> None:
        bad = "ultronultron-basic-userclosed-friend-moa-wrapper-service"
        result = _sanitize_module_path_slug(
            bad,
            domain_slug="closed-friend-task",
            title="挚友MOA包装服务",
            part_index=1,
        )
        assert "ultron" not in result
        assert len(result) <= 45
        assert result == "closed-friend-moa-wrapper-service"


class TestIsPinyinSlug:
    def test_is_pinyin_slug(self) -> None:
        assert is_pinyin_slug("zhi-you-pei-zhi-yu-kuo-zhan")
        assert not is_pinyin_slug("family-task-system")
        assert not is_pinyin_slug("user-data-api-core")

    def test_is_pinyin_slug_rejects_short_english_compound(self) -> None:
        assert not is_pinyin_slug("get-set-add-del-put")

    def test_is_pinyin_slug_rejects_api_slug(self) -> None:
        assert not is_pinyin_slug("user-data-api-v2-svc")

    def test_is_pinyin_slug_still_catches_real_pinyin(self) -> None:
        assert is_pinyin_slug("zhi-you-pei-zhi-yu-kuo-zhan")


class TestSlugCollisionDetection:
    def test_slug_collision_detection(self) -> None:
        used: set[str] = {"family-task"}
        result = resolve_slug_collision("family-task", "family-events", used)
        assert result == "family-events-family-task"
        assert result not in used


class TestSlugTooGeneric:
    def test_slug_too_generic(self) -> None:
        assert is_slug_too_generic("family", "family-system")
        assert is_slug_too_generic("family-system", "family-system")
        assert not is_slug_too_generic("family-task", "family-system")

    def test_slug_too_generic_short_domain_root_not_generic(self) -> None:
        assert not is_slug_too_generic("api", "api-gateway")

    def test_slug_too_generic_still_catches_family(self) -> None:
        assert is_slug_too_generic("family", "family-power-rank")

    def test_resolve_topic_slug_rejects_generic(self) -> None:
        result = resolve_topic_slug(
            "family",
            title="家族任务",
            domain_slug="family-system",
            topic_index=1,
        )
        assert result != "family"
        assert result != "family-system"


class TestResolveTopicSlugE2E:
    def test_resolve_topic_slug_pinyin_fallback(self) -> None:
        result = resolve_topic_slug(
            "zhi-you-pei-zhi-yu-kuo-zhan",
            title="",
            domain_slug="my-domain",
            topic_index=3,
        )
        assert result == "my-domain-topic-3"

    def test_resolve_topic_slug_collision_increment(self) -> None:
        used: set[str] = {"foo", "bar-foo"}
        result = resolve_topic_slug(
            "foo",
            title="Test",
            domain_slug="bar",
            used_slugs=used,
        )
        assert result == "bar-foo-2"

    def test_resolve_topic_slug_used_slugs_written(self) -> None:
        used: set[str] = set()
        result = resolve_topic_slug(
            "family-task",
            title="家族任务",
            domain_slug="family-system",
            used_slugs=used,
        )
        assert result in used
        assert used == {result}
