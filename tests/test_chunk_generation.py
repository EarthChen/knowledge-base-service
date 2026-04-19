"""Integration tests for child chunk generation in CodeGraphBuilder and DocumentIndexer."""

from __future__ import annotations

import pytest

from store.schema import EdgeType, NodeLabel


class TestCodeGraphBuilderChunks:
    """Verify CodeGraphBuilder generates Chunk nodes when enabled."""

    def _make_builder(self, *, enabled: bool = True, **kwargs):
        from indexer.tree_sitter_parser import TreeSitterParser
        from indexer.code_graph_builder import CodeGraphBuilder

        parser = TreeSitterParser()
        return CodeGraphBuilder(
            parser,
            {"python": [".py"]},
            child_chunk_enabled=enabled,
            child_chunk_min_parent_chars=200,
            **kwargs,
        )

    def test_large_function_produces_chunks(self, tmp_path):
        """A .py file with a large function should produce Chunk nodes and PART_OF edges."""
        lines = ["def big_func(x):"]
        for i in range(60):
            lines.append(f"    result_{i} = x * {i}  # compute step {i}")
        lines.append("    return result_0")
        code = "\n".join(lines)

        py_file = tmp_path / "large.py"
        py_file.write_text(code)

        builder = self._make_builder()
        nodes, edges = builder.build_from_file(str(py_file))

        chunk_nodes = [n for n in nodes if n.label == NodeLabel.CHUNK]
        part_of_edges = [e for e in edges if e.edge_type == EdgeType.PART_OF]

        assert len(chunk_nodes) >= 2, f"Expected >=2 chunks, got {len(chunk_nodes)}"
        assert len(part_of_edges) == len(chunk_nodes)

        func_node = next(n for n in nodes if n.label == NodeLabel.FUNCTION)
        for edge in part_of_edges:
            assert edge.target_uid == func_node.uid

        for cn in chunk_nodes:
            assert cn.properties["parent_uid"] == func_node.uid
            assert cn.properties["parent_label"] == str(NodeLabel.FUNCTION)
            assert cn.properties["file"] == str(py_file)
            assert "text" in cn.properties
            assert cn.properties["text"].startswith("// In big_func:")

    def test_small_function_no_chunks(self, tmp_path):
        """A small function should produce no Chunk nodes."""
        code = "def tiny():\n    return 1\n"
        py_file = tmp_path / "small.py"
        py_file.write_text(code)

        builder = self._make_builder()
        nodes, edges = builder.build_from_file(str(py_file))

        chunk_nodes = [n for n in nodes if n.label == NodeLabel.CHUNK]
        assert len(chunk_nodes) == 0

    def test_disabled_produces_no_chunks(self, tmp_path):
        """When child_chunk_enabled=False, no chunks are generated."""
        lines = ["def big_func(x):"]
        for i in range(60):
            lines.append(f"    y_{i} = x + {i}")
        lines.append("    return y_0")
        code = "\n".join(lines)

        py_file = tmp_path / "large.py"
        py_file.write_text(code)

        builder = self._make_builder(enabled=False)
        nodes, edges = builder.build_from_file(str(py_file))

        chunk_nodes = [n for n in nodes if n.label == NodeLabel.CHUNK]
        assert len(chunk_nodes) == 0

    def test_chunk_uid_uniqueness(self, tmp_path):
        """All chunk UIDs within a file should be unique."""
        lines = ["class BigClass:"]
        for i in range(80):
            lines.append(f"    attr_{i} = {i}")
        code = "\n".join(lines)

        py_file = tmp_path / "cls.py"
        py_file.write_text(code)

        builder = self._make_builder()
        nodes, edges = builder.build_from_file(str(py_file))

        chunk_uids = [n.uid for n in nodes if n.label == NodeLabel.CHUNK]
        assert len(chunk_uids) == len(set(chunk_uids))


class TestDocumentIndexerChunks:
    """Verify DocumentIndexer generates Chunk nodes when enabled."""

    def _make_indexer(self, *, enabled: bool = True):
        from indexer.doc_indexer import DocumentIndexer

        return DocumentIndexer(
            exclude_patterns=[],
            child_chunk_enabled=enabled,
            child_chunk_min_parent_chars=200,
        )

    def test_large_doc_section_produces_chunks(self):
        """A markdown doc with a large section should produce Chunk nodes."""
        lines = ["# Big Document\n"]
        lines.append("## Detailed Section\n")
        for i in range(40):
            lines.append(f"Paragraph {i}: " + "word " * 30 + "\n")
        content = "\n".join(lines)

        indexer = self._make_indexer()
        doc = indexer.parse_document("/fake/doc.md", content)
        nodes, edges = indexer.build_graph(doc)

        chunk_nodes = [n for n in nodes if n.label == NodeLabel.CHUNK]
        part_of_edges = [e for e in edges if e.edge_type == EdgeType.PART_OF]

        assert len(chunk_nodes) >= 1, f"Expected >=1 doc chunks, got {len(chunk_nodes)}"
        assert len(part_of_edges) == len(chunk_nodes)

        for cn in chunk_nodes:
            assert cn.properties["parent_label"] == str(NodeLabel.DOCUMENT)
            assert "text" in cn.properties

    def test_small_doc_no_chunks(self):
        """A short markdown doc should produce no Chunk nodes."""
        content = "# Tiny\n\n## Intro\n\nShort content."

        indexer = self._make_indexer()
        doc = indexer.parse_document("/fake/tiny.md", content)
        nodes, edges = indexer.build_graph(doc)

        chunk_nodes = [n for n in nodes if n.label == NodeLabel.CHUNK]
        assert len(chunk_nodes) == 0

    def test_disabled_produces_no_chunks(self):
        """When disabled, no chunks are generated even for large docs."""
        lines = ["# Big Doc\n", "## Section\n"]
        for i in range(40):
            lines.append(f"Line {i}: " + "text " * 30 + "\n")
        content = "\n".join(lines)

        indexer = self._make_indexer(enabled=False)
        doc = indexer.parse_document("/fake/big.md", content)
        nodes, edges = indexer.build_graph(doc)

        chunk_nodes = [n for n in nodes if n.label == NodeLabel.CHUNK]
        assert len(chunk_nodes) == 0
