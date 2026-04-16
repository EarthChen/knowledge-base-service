"""Tests for index quality report."""

import pytest

from indexer.index_report import IndexReport
from store.schema import GraphNode, NodeLabel


class TestIndexReport:
    def test_record_file_success(self):
        r = IndexReport()
        n = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "mod", "file": "a.py", "start_line": 1},
        )
        r.record_file_success("a.py", [n], [])
        assert r.success_files == 1
        assert r.node_counts.get("Module") == 1

    def test_record_file_failure(self):
        r = IndexReport()
        r.record_file_failure("bad.py", "parse error")
        assert r.failed_files == 1
        assert r.failed_file_list == [{"file": "bad.py", "error": "parse error"}]

    def test_finalize_type_coverage(self):
        r = IndexReport()
        typed = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={"name": "t", "file": "f.py", "start_line": 1, "return_type": "str"},
        )
        untyped = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={"name": "u", "file": "f.py", "start_line": 5},
        )
        r.record_file_success("f.py", [typed, untyped], [])
        r.finalize()
        assert r.type_coverage == pytest.approx(0.5)
        assert r.total_files == 1

    def test_to_dict(self):
        r = IndexReport()
        r.duration_seconds = 1.234
        n = GraphNode(
            label=NodeLabel.CLASS,
            properties={"name": "C", "file": "c.py", "start_line": 1},
        )
        r.record_file_success("c.py", [n], [])
        r.finalize()
        d = r.to_dict()
        assert d["total_files"] == 1
        assert d["success_files"] == 1
        assert d["skipped_files"] == 0
        assert d["failed_files"] == 0
        assert d["failed_file_list"] == []
        assert d["node_counts"] == {"Class": 1}
        assert d["edge_counts"] == {}
        assert d["annotation_counts"] == {}
        assert "type_coverage" in d
        assert d["duration_seconds"] == 1.23

    def test_empty_report(self):
        r = IndexReport()
        r.finalize()
        d = r.to_dict()
        assert r.total_files == 0
        assert d["success_files"] == 0
        assert d["type_coverage"] == 0.0
        assert d["node_counts"] == {}
        assert d["failed_file_list"] == []
