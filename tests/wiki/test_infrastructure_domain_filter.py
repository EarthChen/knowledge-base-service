from __future__ import annotations


_DEFAULT_INFRA_KEYWORDS = [
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
]


class TestIsInfraSlug:
    def test_distributed_tracing_two_aspect_modules_filtered(self):
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [
            ("repo", "DistributedTracingAspect"),
            ("repo", "ExceptionInterceptor"),
        ]
        assert _is_infra_slug("distributed-tracing", modules, _DEFAULT_INFRA_KEYWORDS)

    def test_tracing_service_single_trace_aspect_filtered(self):
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [("repo", "TraceAspect")]
        assert _is_infra_slug("tracing-service", modules, _DEFAULT_INFRA_KEYWORDS)

    def test_user_tracing_many_modules_not_filtered(self):
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [("repo", f"UserModule{i}") for i in range(5)]
        assert not _is_infra_slug("user-tracing", modules, _DEFAULT_INFRA_KEYWORDS)

    def test_trace_config_two_modules_filtered(self):
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [("repo", "TraceConfig"), ("repo", "TraceProperties")]
        assert _is_infra_slug("trace-config", modules, _DEFAULT_INFRA_KEYWORDS)

    def test_tracing_three_modules_filtered(self):
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [
            ("repo", "TracingAspect"),
            ("repo", "TraceInterceptor"),
            ("repo", "TraceFilter"),
        ]
        assert _is_infra_slug("distributed-tracing-and-exception-handling", modules, _DEFAULT_INFRA_KEYWORDS)

    def test_four_module_tracing_keyword_not_filtered(self):
        from wiki.nodes.graph_domain_decompose import _is_infra_slug

        modules = [("repo", f"TraceMod{i}") for i in range(4)]
        assert not _is_infra_slug("distributed-tracing", modules, _DEFAULT_INFRA_KEYWORDS)


class TestFilterInfrastructureDomains:
    def test_single_class_domain_merged(self):
        """Domain with exactly 1 PascalCase module is merged into largest neighbor."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "family-core-operations": [("repo", "FamilyCoreService"), ("repo", "FamilyDao")],
            "backdoorserviceimpl": [("repo", "BackDoorServiceImpl")],
        }
        display_names = {
            "family-core-operations": "家族核心运营",
            "backdoorserviceimpl": "后门运维",
        }
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, []
        )
        assert "backdoorserviceimpl" not in result_mapping
        assert "family-core-operations" in result_mapping
        assert len(result_mapping["family-core-operations"]) == 3

    def test_infrastructure_keyword_filtered(self):
        """Domain slug containing infrastructure keyword AND <=3 modules is filtered."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "user-profile": [("repo", "UserService"), ("repo", "ProfileDao")],
            "datasourceconfiguration": [("repo", "DataSourceConfiguration")],
        }
        display_names = {
            "user-profile": "用户资料",
            "datasourceconfiguration": "数据源配置",
        }
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, ["configuration"]
        )
        assert "datasourceconfiguration" not in result_mapping
        assert "user-profile" in result_mapping

    def test_single_class_with_business_suffix_preserved(self):
        """Single PascalCase module with business suffix (Service) is preserved."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "intimacy-service": [("repo", "IntimacyService")],
            "family-core": [("repo", "FamilyManager"), ("repo", "FamilyDao")],
        }
        display_names = {"intimacy-service": "亲密度服务", "family-core": "家族核心"}
        result_map, _ = _filter_infrastructure_domains(domain_mapping, display_names, [])
        assert "intimacy-service" in result_map

    def test_legitimate_domain_preserved(self):
        """Normal multi-module business domain is never filtered."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "family-core-operations": [("repo", "FamilyCoreService"), ("repo", "FamilyDao")],
            "intimacy-relations": [("repo", "IntimacyService"), ("repo", "IntimacyDao")],
        }
        display_names = {
            "family-core-operations": "家族核心运营",
            "intimacy-relations": "亲密度关系",
        }
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, ["configuration"]
        )
        assert len(result_mapping) == 2

    def test_multi_module_domain_not_filtered_by_keyword(self):
        """Multi-module (>3) domain is NOT filtered even if slug matches keyword."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "app-configuration-management": [
                ("r", "ConfigA"),
                ("r", "ConfigB"),
                ("r", "ConfigC"),
                ("r", "ConfigD"),
            ],
        }
        display_names = {"app-configuration-management": "配置管理"}
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, ["configuration"]
        )
        assert "app-configuration-management" in result_mapping

    def test_empty_mapping_handled(self):
        """Empty domain mapping returns unchanged."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        result_mapping, result_names = _filter_infrastructure_domains({}, {}, ["configuration"])
        assert result_mapping == {}

    def test_all_infra_no_crash(self):
        """If all domains are infra, don't crash — return unchanged."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "backdoorserviceimpl": [("repo", "BackDoorServiceImpl")],
        }
        display_names = {"backdoorserviceimpl": "后门"}
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, []
        )
        assert "backdoorserviceimpl" in result_mapping


class TestInfrastructureMergeByCallGraph:
    def test_merge_by_call_edges(self):
        """Infra domain merges into domain with most call edges, not largest."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "business-a": [("repo", "ModuleA1"), ("repo", "ModuleA2")],
            "business-b": [("repo", "ModuleB1"), ("repo", "ModuleB2"), ("repo", "ModuleB3")],
            "DataSourceConfiguration": [("repo", "DataSourceConfiguration")],
        }
        display_names = {
            "business-a": "Business A",
            "business-b": "Business B",
            "DataSourceConfiguration": "DataSourceConfiguration",
        }
        edges = [
            (("repo", "DataSourceConfiguration"), ("repo", "ModuleA1"), 5),
            (("repo", "DataSourceConfiguration"), ("repo", "ModuleB1"), 1),
        ]

        result_map, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, ["configuration"], edges=edges,
        )

        assert "DataSourceConfiguration" not in result_map
        assert ("repo", "DataSourceConfiguration") in result_map["business-a"]

    def test_fallback_to_largest_when_no_edges(self):
        """Falls back to largest domain when no call edges exist for infra module."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "small-domain": [("repo", "M1")],
            "large-domain": [("repo", "M2"), ("repo", "M3"), ("repo", "M4")],
            "InternalServiceAspect": [("repo", "InternalServiceAspect")],
        }
        display_names = {
            "small-domain": "Small",
            "large-domain": "Large",
            "InternalServiceAspect": "InternalServiceAspect",
        }
        edges = [
            (("repo", "M2"), ("repo", "M3"), 3),
        ]

        result_map, _ = _filter_infrastructure_domains(
            domain_mapping, display_names, ["aspect"], edges=edges,
        )

        assert "InternalServiceAspect" not in result_map
        assert ("repo", "InternalServiceAspect") in result_map["large-domain"]

    def test_reverse_edge_direction_counted(self):
        """Reverse edges (target → infra) also counted for merge decision."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "domain-x": [("repo", "X1"), ("repo", "X2")],
            "domain-y": [("repo", "Y1"), ("repo", "Y2")],
            "package-type-handler": [("repo", "PackageTypeHandler")],
        }
        display_names = {"domain-x": "X", "domain-y": "Y", "package-type-handler": "PackageTypeHandler"}
        edges = [
            (("repo", "Y1"), ("repo", "PackageTypeHandler"), 10),
        ]

        result_map, _ = _filter_infrastructure_domains(
            domain_mapping, display_names, ["package-info"], edges=edges,
        )

        assert "package-type-handler" not in result_map
        assert ("repo", "PackageTypeHandler") in result_map["domain-y"]
