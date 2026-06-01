"""Tests for infrastructure module detection in graph_domain_decompose (T2-10)."""

from __future__ import annotations

from core.config import get_settings
from wiki.nodes.graph_domain_decompose import (
    _detect_infra_modules,
    _is_infra_module_path,
    _reassign_infra_modules,
)


class TestInfraModulePath:
    def test_infra_module_detected_by_path(self) -> None:
        patterns = get_settings().wiki.infra_module_patterns
        assert _is_infra_module_path("src/main/java/com/app/core/config.py", patterns)

    def test_business_module_not_marked_infra(self) -> None:
        patterns = get_settings().wiki.infra_module_patterns
        assert not _is_infra_module_path("src/main/java/com/app/orders/service.py", patterns)

    def test_infra_patterns_configurable(self) -> None:
        custom = ["vendor/sdk/"]
        assert _is_infra_module_path("vendor/sdk/client.py", custom)
        assert not _is_infra_module_path("orders/service.py", custom)


class TestInfraModuleFanIn:
    def test_infra_module_detected_by_fan_in(self) -> None:
        modules = [("repo", f"Mod{i}") for i in range(6)]
        mod_set = set(modules)
        hub = ("repo", "SharedUtil")
        edges = [
            ((repo, f"Mod{i}"), hub, 1)
            for i in range(5)
            for repo in ("repo",)
        ]
        detected = _detect_infra_modules(
            list(mod_set | {hub}),
            {f"repo|SharedUtil": "src/utils/SharedUtil.java"},
            edges,
            path_patterns=[],
            fan_in_threshold=0.5,
        )
        assert hub in detected
        assert ("repo", "Mod0") not in detected

    def test_business_module_not_marked_infra_by_fan_in_alone(self) -> None:
        modules = [("repo", f"Mod{i}") for i in range(10)]
        edges = [((repo, "Mod0"), (repo, "Mod1"), 1) for repo in ("repo",)]
        detected = _detect_infra_modules(
            modules,
            {f"repo|Mod{i}": f"src/orders/Mod{i}.java" for i in range(10)},
            edges,
            path_patterns=[],
            fan_in_threshold=0.5,
        )
        assert detected == set()


class TestReassignInfraModules:
    def test_reassign_creates_infrastructure_domain(self) -> None:
        mapping = {"orders": [("repo", "OrderService"), ("repo", "ConfigHelper")]}
        display = {"orders": "Orders"}
        infra = {("repo", "ConfigHelper")}
        _reassign_infra_modules(mapping, display, infra, "__infrastructure__")
        assert ("repo", "OrderService") in mapping["orders"]
        assert ("repo", "ConfigHelper") not in mapping["orders"]
        infra_slug = next(k for k in mapping if k != "orders")
        assert ("repo", "ConfigHelper") in mapping[infra_slug]
        assert display[infra_slug] == "__infrastructure__"
