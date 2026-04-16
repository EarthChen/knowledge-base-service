"""Tests for AnalysisService (impact analysis + index consistency)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from query.analysis_service import (
    AnalysisService,
    ConsistencyReport,
    ImpactReport,
    _coerce_unix_ts,
    _collect_repo_files_sync,
    _is_entry_point,
    _norm_repo_relative_key,
)


class TestImpactReport:
    def test_empty_report(self):
        r = ImpactReport(
            changed_functions=[],
            direct_callers=[],
            transitive_callers=[],
            affected_classes=[],
            affected_layers=[],
            affected_entry_points=[],
            max_depth_reached=False,
        )
        d = r.to_dict()
        assert d["total_affected"] == 0
        assert d["max_depth_reached"] is False

    def test_to_dict_deduplicates_classes(self):
        r = ImpactReport(
            changed_functions=["foo"],
            direct_callers=[{"name": "bar"}],
            transitive_callers=[],
            affected_classes=["A", "A", "B"],
            affected_layers=["business", "business"],
            affected_entry_points=[],
            max_depth_reached=True,
        )
        d = r.to_dict()
        assert set(d["affected_classes"]) == {"A", "B"}
        assert set(d["affected_layers"]) == {"business"}
        assert d["total_affected"] == 1
        assert d["max_depth_reached"] is True


class TestConsistencyReport:
    def test_consistent(self):
        r = ConsistencyReport(
            total_graph_files=5,
            total_repo_files=5,
            ghost_files=[],
            missing_files=[],
            stale_files=[],
            is_consistent=True,
        )
        d = r.to_dict()
        assert d["is_consistent"] is True
        assert d["total_graph_files"] == 5

    def test_truncates_at_100(self):
        ghosts = [f"ghost_{i}.py" for i in range(150)]
        r = ConsistencyReport(
            total_graph_files=150,
            total_repo_files=0,
            ghost_files=ghosts,
            missing_files=[],
            stale_files=[],
            is_consistent=False,
        )
        d = r.to_dict()
        assert len(d["ghost_files"]) == 100


class TestCoerceUnixTs:
    def test_seconds(self):
        assert _coerce_unix_ts(1700000000.0) == 1700000000.0

    def test_milliseconds(self):
        result = _coerce_unix_ts(1700000000000.0)
        assert result == pytest.approx(1700000000.0)

    def test_none(self):
        assert _coerce_unix_ts(None) is None

    def test_invalid_string(self):
        assert _coerce_unix_ts("not_a_number") is None

    def test_int_input(self):
        assert _coerce_unix_ts(1700000000) == 1700000000.0


class TestIsEntryPoint:
    def test_http_endpoint_is_entry(self):
        assert _is_entry_point(["http_endpoint"], None) is True

    def test_rpc_consumer_is_entry(self):
        assert _is_entry_point(["rpc_consumer"], None) is True

    def test_message_listener_is_entry(self):
        assert _is_entry_point(["message_listener"], None) is True

    def test_class_controller_is_entry(self):
        assert _is_entry_point(None, ["http_controller"]) is True

    def test_class_rpc_provider_is_entry(self):
        assert _is_entry_point(None, ["rpc_provider"]) is True

    def test_plain_not_entry(self):
        assert _is_entry_point(["service"], None) is False

    def test_none_not_entry(self):
        assert _is_entry_point(None, None) is False


class TestNormRepoRelativeKey:
    def test_relative_path(self):
        root = Path("/repo")
        key = _norm_repo_relative_key(root, "src/main.py")
        assert key is not None
        assert key == "src/main.py" or key.endswith("src/main.py")

    def test_empty_path(self):
        assert _norm_repo_relative_key(Path("/repo"), "") is None

    def test_whitespace_path(self):
        assert _norm_repo_relative_key(Path("/repo"), "   ") is None


class TestCollectRepoFilesSync:
    def test_collects_supported_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("pass")
            (root / "app.js").write_text("var x;")
            (root / "data.csv").write_text("a,b")

            result = _collect_repo_files_sync(root, {".py", ".js"}, set())
            assert "main.py" in result
            assert "app.js" in result
            assert "data.csv" not in result

    def test_excludes_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("pass")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "dep.js").write_text("var x;")

            result = _collect_repo_files_sync(root, {".py", ".js"}, {"node_modules"})
            assert any("main.py" in f for f in result)
            assert not any("dep.js" in f for f in result)

    def test_nonexistent_dir(self):
        result = _collect_repo_files_sync(Path("/nonexistent"), {".py"}, set())
        assert result == set()


class TestAnalysisServiceImpact:
    @pytest.fixture
    def mock_store(self):
        store = MagicMock()
        store.execute_query = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_empty_changed_functions(self, mock_store):
        svc = AnalysisService(mock_store)
        report = await svc.analyze_impact([])
        assert report.changed_functions == []
        assert report.direct_callers == []
        assert report.transitive_callers == []
        mock_store.execute_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_callers(self, mock_store):
        mock_store.execute_query.return_value = MagicMock(
            data=[
                {
                    "caller_uid": "uid1",
                    "caller_name": "callA",
                    "caller_file": "a.py",
                    "caller_fqn": "mod.callA",
                    "caller_semantic_roles": None,
                    "caller_architecture_layer": "business",
                    "parent_class_name": "ServiceA",
                    "parent_class_semantic_roles": None,
                    "depth": 1,
                    "target_name": "foo",
                },
                {
                    "caller_uid": "uid2",
                    "caller_name": "callB",
                    "caller_file": "b.py",
                    "caller_fqn": "mod.callB",
                    "caller_semantic_roles": None,
                    "caller_architecture_layer": "presentation",
                    "parent_class_name": "ControllerB",
                    "parent_class_semantic_roles": None,
                    "depth": 3,
                    "target_name": "foo",
                },
            ]
        )
        svc = AnalysisService(mock_store)
        report = await svc.analyze_impact(["foo"], max_depth=5)
        assert len(report.direct_callers) == 1
        assert report.direct_callers[0]["name"] == "callA"
        assert len(report.transitive_callers) == 1
        assert report.transitive_callers[0]["name"] == "callB"
        assert "ServiceA" in report.affected_classes
        assert "ControllerB" in report.affected_classes
        d = report.to_dict()
        assert d["total_affected"] == 2

    @pytest.mark.asyncio
    async def test_entry_points_detected(self, mock_store):
        mock_store.execute_query.return_value = MagicMock(
            data=[
                {
                    "caller_uid": "uid_ep",
                    "caller_name": "handleRequest",
                    "caller_file": "ctrl.py",
                    "caller_fqn": None,
                    "caller_semantic_roles": ["http_endpoint"],
                    "caller_architecture_layer": "presentation",
                    "parent_class_name": "UserController",
                    "parent_class_semantic_roles": ["http_controller"],
                    "depth": 2,
                    "target_name": "compute",
                },
            ]
        )
        svc = AnalysisService(mock_store)
        report = await svc.analyze_impact(["compute"])
        assert len(report.affected_entry_points) == 1
        assert report.affected_entry_points[0]["name"] == "handleRequest"

    @pytest.mark.asyncio
    async def test_max_depth_reached(self, mock_store):
        mock_store.execute_query.return_value = MagicMock(
            data=[
                {
                    "caller_uid": "uid_deep",
                    "caller_name": "deep",
                    "caller_file": "d.py",
                    "caller_fqn": None,
                    "caller_semantic_roles": None,
                    "caller_architecture_layer": None,
                    "parent_class_name": None,
                    "parent_class_semantic_roles": None,
                    "depth": 3,
                    "target_name": "foo",
                },
            ]
        )
        svc = AnalysisService(mock_store)
        report = await svc.analyze_impact(["foo"], max_depth=3)
        assert report.max_depth_reached is True


class TestAnalysisServiceConsistency:
    @pytest.fixture
    def mock_store(self):
        store = MagicMock()
        store.execute_query = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_nonexistent_repo_path(self, mock_store):
        mock_store.execute_query.return_value = MagicMock(data=[{"file_path": "main.py"}])
        svc = AnalysisService(mock_store)
        report = await svc.verify_consistency("/nonexistent/repo")
        assert report.total_repo_files == 0
        assert len(report.ghost_files) >= 1

    @pytest.mark.asyncio
    async def test_consistent_repo(self, mock_store):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("pass")

            mock_store.execute_query.side_effect = [
                MagicMock(data=[{"file_path": "main.py"}]),
                MagicMock(data=[]),
            ]
            svc = AnalysisService(mock_store)
            report = await svc.verify_consistency(tmpdir)
            assert report.is_consistent is True
            assert report.ghost_files == []
            assert report.missing_files == []

    @pytest.mark.asyncio
    async def test_ghost_and_missing_files(self, mock_store):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "existing.py").write_text("pass")

            mock_store.execute_query.side_effect = [
                MagicMock(data=[{"file_path": "deleted.py"}]),
                MagicMock(data=[]),
            ]
            svc = AnalysisService(mock_store)
            report = await svc.verify_consistency(tmpdir)
            assert "deleted.py" in report.ghost_files
            assert "existing.py" in report.missing_files
            assert report.is_consistent is False
