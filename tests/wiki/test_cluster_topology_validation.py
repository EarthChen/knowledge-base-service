"""Tests for cluster topology scatter validation (G8)."""

from __future__ import annotations

import pytest

from wiki.cluster_validation import (
    ClusterScatterReport,
    _extract_top_business_dir,
    validate_cluster_topology,
)


def _community(*modules: tuple[str, str]) -> set[tuple[str, str]]:
    return set(modules)


class TestExtractTopBusinessDir:
    def test_generic_dirs_filtered(self) -> None:
        path = "src/main/java/com/org/example/payment/Service.java"
        assert _extract_top_business_dir(path) == "example"

    def test_empty_path_returns_root(self) -> None:
        assert _extract_top_business_dir("") == "root"


class TestValidateClusterTopology:
    def test_coherent_cluster_not_flagged(self) -> None:
        repo = "my-repo"
        modules = [(repo, f"mod-{i}") for i in range(5)]
        community = [_community(*modules)]
        module_paths = {
            f"{repo}|mod-{i}": f"src/main/java/com/payment/Mod{i}.java"
            for i in range(5)
        }

        reports = validate_cluster_topology(community, module_paths)

        assert reports == []

    def test_scattered_cluster_flagged(self) -> None:
        repo = "my-repo"
        top_dirs = ["payment", "user", "order", "inventory", "billing", "shipping"]
        modules = [(repo, f"mod-{i}") for i in range(6)]
        community = [_community(*modules)]
        module_paths = {
            f"{repo}|mod-{i}": f"src/main/java/com/{top_dirs[i]}/Mod{i}.java"
            for i in range(6)
        }

        reports = validate_cluster_topology(community, module_paths)

        assert len(reports) == 1
        report = reports[0]
        assert report.is_scattered is True
        assert report.module_count == 6
        assert report.unique_top_dirs == 6
        assert report.scatter_ratio == pytest.approx(1.0)
        assert set(report.top_dirs) == set(top_dirs)

    def test_small_cluster_skipped(self) -> None:
        repo = "my-repo"
        modules = [(repo, "mod-a"), (repo, "mod-b")]
        community = [_community(*modules)]
        module_paths = {
            f"{repo}|mod-a": "src/main/java/com/payment/ModA.java",
            f"{repo}|mod-b": "src/main/java/com/user/ModB.java",
        }

        reports = validate_cluster_topology(community, module_paths, min_modules_for_check=4)

        assert reports == []

    def test_scatter_ratio_calculation(self) -> None:
        repo = "my-repo"
        modules = [(repo, f"mod-{i}") for i in range(4)]
        community = [_community(*modules)]
        module_paths = {
            f"{repo}|mod-0": "src/main/java/com/payment/Mod0.java",
            f"{repo}|mod-1": "src/main/java/com/payment/Mod1.java",
            f"{repo}|mod-2": "src/main/java/com/user/Mod2.java",
            f"{repo}|mod-3": "src/main/java/com/order/Mod3.java",
        }

        reports = validate_cluster_topology(
            community,
            module_paths,
            scatter_threshold=0.7,
            min_modules_for_check=4,
        )

        assert len(reports) == 1
        report = reports[0]
        assert report.scatter_ratio == pytest.approx(0.75)
        assert report.unique_top_dirs == 3
        assert report.module_count == 4

    def test_empty_paths_handled(self) -> None:
        repo = "my-repo"
        modules = [(repo, f"mod-{i}") for i in range(4)]
        community = [_community(*modules)]
        module_paths: dict[str, str] = {}

        reports = validate_cluster_topology(community, module_paths, min_modules_for_check=4)

        assert reports == []

    def test_threshold_boundary(self) -> None:
        repo = "my-repo"
        modules = [(repo, f"mod-{i}") for i in range(5)]
        community = [_community(*modules)]
        # 3 unique top dirs / 5 modules = 0.6 exactly
        module_paths = {
            f"{repo}|mod-0": "src/main/java/com/payment/Mod0.java",
            f"{repo}|mod-1": "src/main/java/com/payment/Mod1.java",
            f"{repo}|mod-2": "src/main/java/com/user/Mod2.java",
            f"{repo}|mod-3": "src/main/java/com/order/Mod3.java",
            f"{repo}|mod-4": "src/main/java/com/order/Mod4.java",
        }

        at_threshold = validate_cluster_topology(
            community,
            module_paths,
            scatter_threshold=0.6,
            min_modules_for_check=4,
        )
        assert at_threshold == []

        above_threshold = validate_cluster_topology(
            community,
            module_paths,
            scatter_threshold=0.59,
            min_modules_for_check=4,
        )
        assert len(above_threshold) == 1
        assert above_threshold[0].scatter_ratio == pytest.approx(0.6)

    def test_report_type(self) -> None:
        repo = "my-repo"
        top_dirs = ["a", "b", "c", "d", "e", "f"]
        modules = [(repo, f"mod-{i}") for i in range(6)]
        community = [_community(*modules)]
        module_paths = {
            f"{repo}|mod-{i}": f"src/main/java/com/{top_dirs[i]}/Mod{i}.java"
            for i in range(6)
        }

        reports = validate_cluster_topology(community, module_paths)

        assert all(isinstance(r, ClusterScatterReport) for r in reports)
