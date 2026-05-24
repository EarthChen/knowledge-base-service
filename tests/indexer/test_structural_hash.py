"""Unit tests for API-surface structural hashing (incremental COSMETIC vs STRUCTURAL)."""

from __future__ import annotations

import re

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _fn(
    name: str = "foo",
    *,
    signature: str = "def foo():",
    parameters: str | list[str] = "",
    return_type: str = "",
    docstring: str = "",
    code_snippet: str = "def foo():\n    pass",
) -> GraphNode:
    props: dict = {
        "name": name,
        "signature": signature,
        "file": "m.py",
        "start_line": 1,
        "docstring": docstring,
        "code_snippet": code_snippet,
    }
    if parameters:
        props["parameters"] = parameters
    if return_type:
        props["return_type"] = return_type
    return GraphNode(label=NodeLabel.FUNCTION, properties=props)


def _cls(
    name: str = "Bar",
    *,
    base_classes: str | list[str] = "",
    interfaces: str | list[str] = "",
    docstring: str = "",
) -> GraphNode:
    props: dict = {"name": name, "file": "m.py", "start_line": 1, "docstring": docstring}
    if base_classes:
        props["base_classes"] = base_classes
    if interfaces:
        props["interfaces"] = interfaces
    return GraphNode(label=NodeLabel.CLASS, properties=props)


class TestComputeStructuralHash:
    def test_same_signature_same_hash(self) -> None:
        from indexer.structural_hash import compute_structural_hash

        a = _fn(docstring="old doc", code_snippet="def foo():\n    return 1")
        b = _fn(docstring="new doc", code_snippet="def foo():\n    return 99")
        assert compute_structural_hash([a], [], []) == compute_structural_hash([b], [], [])

    def test_different_signature_different_hash(self) -> None:
        from indexer.structural_hash import compute_structural_hash

        a = _fn(parameters="x: int")
        b = _fn(parameters="x: str")
        assert compute_structural_hash([a], [], []) != compute_structural_hash([b], [], [])

    def test_order_independent(self) -> None:
        from indexer.structural_hash import compute_structural_hash

        f1 = _fn("alpha", signature="def alpha():")
        f2 = _fn("beta", signature="def beta():")
        h1 = compute_structural_hash([f1, f2], [], [])
        h2 = compute_structural_hash([f2, f1], [], [])
        assert h1 == h2

    def test_class_base_change(self) -> None:
        from indexer.structural_hash import compute_structural_hash

        a = _cls(base_classes=["Base"])
        b = _cls(base_classes=["Other"])
        assert compute_structural_hash([], [a], []) != compute_structural_hash([], [b], [])

    def test_import_change(self) -> None:
        from indexer.structural_hash import compute_structural_hash

        imp_a = GraphEdge(EdgeType.IMPORTS, "Module:m.py:m:0", "Module:os:0")
        imp_b = GraphEdge(EdgeType.IMPORTS, "Module:m.py:m:0", "Module:sys:0")
        assert compute_structural_hash([], [], [imp_a]) != compute_structural_hash([], [], [imp_b])

    def test_empty_inputs(self) -> None:
        from indexer.structural_hash import compute_structural_hash

        h = compute_structural_hash([], [], [])
        assert HEX64.match(h)


class TestChangeLevel:
    def test_change_level_values(self) -> None:
        from indexer.structural_hash import ChangeLevel

        assert ChangeLevel.NONE == "none"
        assert ChangeLevel.COSMETIC == "cosmetic"
        assert ChangeLevel.STRUCTURAL == "structural"
