"""Tests for code_hash on Module nodes."""
import hashlib
from pathlib import Path

from indexer.code_graph_builder import CodeGraphBuilder
from indexer.tree_sitter_parser import TreeSitterParser
from store.schema import NodeLabel


def test_module_node_has_code_hash(tmp_path: Path) -> None:
    """Module node should contain a code_hash property after build."""
    src = tmp_path / "hello.py"
    src.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    parser = TreeSitterParser()
    builder = CodeGraphBuilder(parser, {"python": [".py"]})
    content = src.read_text(encoding="utf-8")
    nodes, _edges = builder.build_from_file(str(src), content, store_path="hello.py")

    mod_nodes = [n for n in nodes if n.label == NodeLabel.MODULE]
    assert len(mod_nodes) == 1
    mod = mod_nodes[0]

    expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert mod.properties.get("code_hash") == expected_hash


def test_code_hash_deterministic(tmp_path: Path) -> None:
    """Same content should always produce the same hash."""
    src = tmp_path / "stable.py"
    content = "x = 1\n"
    src.write_text(content, encoding="utf-8")

    parser = TreeSitterParser()
    builder = CodeGraphBuilder(parser, {"python": [".py"]})

    nodes1, _ = builder.build_from_file(str(src), content, store_path="stable.py")
    nodes2, _ = builder.build_from_file(str(src), content, store_path="stable.py")

    hash1 = [n for n in nodes1 if n.label == NodeLabel.MODULE][0].properties["code_hash"]
    hash2 = [n for n in nodes2 if n.label == NodeLabel.MODULE][0].properties["code_hash"]
    assert hash1 == hash2


def test_code_hash_changes_on_content_change(tmp_path: Path) -> None:
    """Different content should produce a different hash."""
    src = tmp_path / "changing.py"
    parser = TreeSitterParser()
    builder = CodeGraphBuilder(parser, {"python": [".py"]})

    content_v1 = "x = 1\n"
    src.write_text(content_v1, encoding="utf-8")
    nodes1, _ = builder.build_from_file(str(src), content_v1, store_path="changing.py")
    hash1 = [n for n in nodes1 if n.label == NodeLabel.MODULE][0].properties["code_hash"]

    content_v2 = "x = 2\n"
    src.write_text(content_v2, encoding="utf-8")
    nodes2, _ = builder.build_from_file(str(src), content_v2, store_path="changing.py")
    hash2 = [n for n in nodes2 if n.label == NodeLabel.MODULE][0].properties["code_hash"]

    assert hash1 != hash2
