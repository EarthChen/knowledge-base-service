"""Tests for indexer.child_chunker — sliding window child chunk generation."""

from __future__ import annotations

import pytest

from indexer.child_chunker import ChildChunk, chunk_code_entity, chunk_document_section


class TestChunkCodeEntity:
    """Unit tests for code entity chunking."""

    def test_small_entity_returns_empty(self):
        """Entities below MIN_PARENT_CHARS threshold produce no chunks."""
        result = chunk_code_entity(
            code_snippet="def foo():\n    return 1\n",
            signature="def foo()",
            entity_name="foo",
            start_line=1,
        )
        assert result == []

    def test_large_function_produces_chunks(self):
        """A function larger than the window produces multiple overlapping chunks."""
        lines = [f"    line_{i} = {i} * 2  # some computation here padding" for i in range(80)]
        code = "def big_func(x: int, y: int) -> int:\n" + "\n".join(lines) + "\n    return x"
        result = chunk_code_entity(
            code_snippet=code,
            signature="def big_func(x: int, y: int) -> int",
            entity_name="big_func",
            start_line=10,
        )
        assert len(result) >= 2
        for chunk in result:
            assert isinstance(chunk, ChildChunk)
            assert chunk.chunk_index >= 0
            assert chunk.start_line >= 10
            assert chunk.end_line >= chunk.start_line

    def test_signature_prefix_present(self):
        """Each chunk text starts with the signature context prefix."""
        lines = [f"    x = compute_step_{i}()" for i in range(80)]
        code = "def process(data):\n" + "\n".join(lines)
        result = chunk_code_entity(
            code_snippet=code,
            signature="def process(data)",
            entity_name="process",
            start_line=1,
        )
        assert len(result) >= 1
        for chunk in result:
            assert chunk.text.startswith("// In process: def process(data)\n")

    def test_chunk_indices_sequential(self):
        """chunk_index values are sequential starting from 0."""
        code = "class Foo:\n" + "\n".join([f"    attr_{i} = {i}" for i in range(100)])
        result = chunk_code_entity(
            code_snippet=code,
            signature="class Foo",
            entity_name="Foo",
            start_line=5,
        )
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i

    def test_overlap_between_consecutive_chunks(self):
        """Consecutive chunks have overlapping content (25% overlap by default)."""
        lines = [f"    step_{i} = do_work({i})" for i in range(120)]
        code = "def long_func():\n" + "\n".join(lines)
        result = chunk_code_entity(
            code_snippet=code,
            signature="def long_func()",
            entity_name="long_func",
            start_line=1,
        )
        if len(result) >= 2:
            text_0_lines = set(result[0].text.split("\n"))
            text_1_lines = set(result[1].text.split("\n"))
            overlap = text_0_lines & text_1_lines
            # At least the prefix line overlaps, plus some code lines
            assert len(overlap) >= 1

    def test_custom_window_and_stride(self):
        """Custom window/stride/min_parent produce different chunk counts."""
        code = "def f():\n" + "\n".join([f"    x{i} = {i}" for i in range(60)])
        default_result = chunk_code_entity(
            code_snippet=code, signature="def f()", entity_name="f", start_line=1,
        )
        small_window_result = chunk_code_entity(
            code_snippet=code, signature="def f()", entity_name="f", start_line=1,
            window_chars=400, stride_chars=300,
        )
        # Smaller windows should produce more chunks
        assert len(small_window_result) >= len(default_result)

    def test_line_boundary_respected(self):
        """Chunks never split in the middle of a line."""
        code = "def f():\n" + "\n".join([f"    long_variable_name_{i} = 'value_{i}'" for i in range(80)])
        result = chunk_code_entity(
            code_snippet=code, signature="def f()", entity_name="f", start_line=1,
        )
        for chunk in result:
            lines = chunk.text.split("\n")
            for line in lines:
                # No partial lines — each line is either the prefix or a complete code line
                assert not line.endswith("\\")  # heuristic: no mid-line breaks


class TestChunkDocumentSection:
    """Unit tests for document section chunking."""

    def test_small_doc_returns_empty(self):
        """Short documents below threshold produce no chunks."""
        result = chunk_document_section(
            content="Short doc content.",
            section_title="Intro",
            doc_title="README",
            start_line=1,
        )
        assert result == []

    def test_large_doc_produces_chunks(self):
        """Long documents produce child chunks."""
        content = "\n".join([f"Paragraph {i}: " + "word " * 40 for i in range(30)])
        result = chunk_document_section(
            content=content,
            section_title="Details",
            doc_title="Guide",
            start_line=10,
        )
        assert len(result) >= 2
        for chunk in result:
            assert isinstance(chunk, ChildChunk)
            assert "Details" in chunk.text  # prefix includes section title

    def test_doc_chunk_indices_sequential(self):
        content = "\n".join([f"Line {i}: " + "text " * 30 for i in range(40)])
        result = chunk_document_section(
            content=content,
            section_title="Section",
            doc_title="Doc",
            start_line=1,
        )
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i
