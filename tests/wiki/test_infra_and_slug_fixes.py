from __future__ import annotations

_INFRA_KEYWORDS = [
    "configuration",
    "typehandler",
    "aspect",
    "package-info",
    "wrapper",
    "handler",
    "executor",
    "debug",
    "groovy",
    "impl",
    "tracing",
    "trace",
    "aop",
    "interceptor",
    "log-trace",
    "exception-handling",
    "error-handler",
    "health-check",
    "graceful-shutdown",
    "circuit-breaker",
    "rate-limit",
    "retry-policy",
]


class TestInfraSlugExpansion:
    def test_infra_slug_detects_log_trace(self) -> None:
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [("repo", "LogTraceAspect"), ("repo", "ExceptionHandler")]
        assert _is_infra_slug("log-trace-and-exception-handling", modules, _INFRA_KEYWORDS)

    def test_infra_slug_detects_health_check(self) -> None:
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [("repo", "HealthCheckEndpoint")]
        assert _is_infra_slug("health-check", modules, _INFRA_KEYWORDS)

    def test_infra_slug_allows_business_domain(self) -> None:
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [("repo", "FamilyService"), ("repo", "FamilyDao"), ("repo", "FamilyManager")]
        assert not _is_infra_slug("family-system", modules, _INFRA_KEYWORDS)


class TestTopicSlugEnglishEnforcement:
    def test_normalize_pinyin_slug(self) -> None:
        from wiki.path_conventions import _normalize_topic_slug

        result = _normalize_topic_slug("jia-zu-guan-xi-yu-huo-yue-tong-bu", "家族关系与活跃同步")
        assert result == "family-relation-activity-sync"

    def test_normalize_module_path_slug(self) -> None:
        from wiki.path_conventions import _normalize_topic_slug

        result = _normalize_topic_slug(
            "ultronultron-basic-userbasic-user-privilege-domain-repo-v2",
            "用户权益",
        )
        assert result == "user-privilege"

    def test_preserve_good_slug(self) -> None:
        from wiki.path_conventions import _normalize_topic_slug

        assert _normalize_topic_slug("family-system", "Family System") == "family-system"

    def test_title_to_slug_basic(self) -> None:
        from wiki.path_conventions import _title_to_slug

        assert _title_to_slug("家族关系管理") == "family-relation-management"
