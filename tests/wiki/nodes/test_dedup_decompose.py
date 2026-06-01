"""Tests for domain decomposition dedup fixes."""

from __future__ import annotations

from wiki.nodes.graph_domain_decompose import (
    _dedup_parallel_naming_results,
    _dedup_sub_domains,
)


class TestDedupParallelNamingNoHash:
    """Verify that numeric suffix is used instead of MD5 hash."""

    def test_collision_without_modules_merges(self):
        results = [
            {"slug": "intimacy-relations", "display_name": "亲密度关系", "description": "Core"},
            {"slug": "intimacy-relations", "display_name": "亲密度关系管理", "description": "Management"},
        ]
        deduped = _dedup_parallel_naming_results(results, existing_slugs=[])
        slugs = [r["slug"] for r in deduped]
        assert len(deduped) == 1
        assert "intimacy-relations" in slugs

    def test_collision_with_modules_merges(self):
        results = [
            {"slug": "user-service", "display_name": "用户服务", "modules": ["com.user.AuthService"]},
            {"slug": "user-service", "display_name": "用户服务2", "modules": ["com.user.ProfileService"]},
        ]
        deduped = _dedup_parallel_naming_results(results, existing_slugs=[])
        assert len(deduped) == 1
        assert deduped[0]["slug"] == "user-service"
        assert "com.user.AuthService" in deduped[0]["modules"]
        assert "com.user.ProfileService" in deduped[0]["modules"]


class TestDedupSubDomainsAncestorAware:
    """Verify that （核心） is not duplicated across levels."""

    def test_no_duplicate_core_suffix(self):
        sub_domains = [
            {"slug": "intimacy-relations", "display_name": "亲密度关系", "description": "核心关系管理"},
        ]
        result = _dedup_sub_domains(
            sub_domains,
            parent_display_name="亲密度关系",
            ancestor_display_names={"亲密度关系（核心）"},
        )
        for sub in result:
            assert sub["display_name"] != "亲密度关系（核心）", (
                "Should not duplicate ancestor's （核心） suffix"
            )

    def test_single_level_dedup_still_works(self):
        sub_domains = [
            {"slug": "user-auth", "display_name": "用户认证", "description": "认证模块"},
        ]
        result = _dedup_sub_domains(
            sub_domains,
            parent_display_name="用户认证",
        )
        assert result[0]["display_name"] != "用户认证"
