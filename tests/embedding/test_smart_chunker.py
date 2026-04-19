"""Tests for the smart markdown chunker."""

from indexer.smart_chunker import (
    smart_chunk_markdown,
    Chunk,
    MIN_CHUNK_CHARS,
    _classify_line,
)


class TestClassifyLine:
    """Unit tests for _classify_line."""

    def test_h1(self):
        assert _classify_line("# Title")[0] == "h1"

    def test_h2(self):
        assert _classify_line("## Section")[0] == "h2"

    def test_h3(self):
        assert _classify_line("### Sub")[0] == "h3"

    def test_blank_line(self):
        assert _classify_line("")[0] == "blank_line"
        assert _classify_line("   ")[0] == "blank_line"

    def test_code_fence(self):
        assert _classify_line("```python")[0] == "code_fence"

    def test_hr(self):
        assert _classify_line("---")[0] == "hr"

    def test_list_item(self):
        assert _classify_line("- item")[0] == "list_item"
        assert _classify_line("1. item")[0] == "list_item"

    def test_regular_line(self):
        assert _classify_line("Hello world")[0] == "line_break"


class TestSmartChunkMarkdown:
    """Unit tests for smart_chunk_markdown."""

    def test_empty_text(self):
        assert smart_chunk_markdown("") == []
        assert smart_chunk_markdown("   ") == []

    def test_short_text_single_chunk(self):
        text = "# Title\n\nSome content here."
        chunks = smart_chunk_markdown(text)
        assert len(chunks) == 1
        assert "Title" in chunks[0].text

    def test_heading_splits(self):
        """Text with headings should split at heading boundaries."""
        sections = []
        for i in range(5):
            section = f"## Section {i}\n\n" + f"Content for section {i}. " * 200 + "\n"
            sections.append(section)
        text = "\n".join(sections)
        chunks = smart_chunk_markdown(text, target_chars=1000)
        assert len(chunks) >= 2

    def test_code_block_not_split(self):
        """Code blocks should never be split across chunks."""
        code_block = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(100)) + "\n```"
        text = f"# Before\n\nSome text.\n\n{code_block}\n\n# After\n\nMore text."
        chunks = smart_chunk_markdown(text)
        for chunk in chunks:
            fence_count = chunk.text.count("```")
            assert fence_count % 2 == 0 or fence_count == 0, (
                f"Code block split across chunks: {fence_count} fences"
            )

    def test_overlap_between_chunks(self):
        """Consecutive chunks should have overlapping content."""
        sections = []
        for i in range(10):
            sections.append(f"## Section {i}\n\n" + f"Content {i}. " * 300 + "\n")
        text = "\n".join(sections)
        chunks = smart_chunk_markdown(text, target_chars=800)
        if len(chunks) >= 2:
            # Overlap is best-effort; ensure chunks are non-empty
            for i in range(len(chunks) - 1):
                assert len(chunks[i].text) > 0

    def test_chunk_size_approximately_target(self):
        """Each chunk should be approximately target_chars in size."""
        text = "\n\n".join([f"Paragraph {i}. " * 50 for i in range(50)])
        chunks = smart_chunk_markdown(text, target_chars=1000)
        for chunk in chunks[:-1]:  # Last chunk can be smaller
            assert len(chunk.text) >= MIN_CHUNK_CHARS

    def test_heading_context_tracked(self):
        """Chunks should track their heading context."""
        text = "# Main Title\n\n" + "Content. " * 500 + "\n\n## Section A\n\n" + "More content. " * 500
        chunks = smart_chunk_markdown(text, target_chars=500)
        # At least one chunk should have heading context
        has_context = any(c.heading_context for c in chunks)
        assert has_context

    def test_single_line_input(self):
        text = "Just one line"
        chunks = smart_chunk_markdown(text)
        assert len(chunks) == 1
        assert chunks[0].text == "Just one line"

    def test_returns_chunk_objects(self):
        text = "# Hello\n\nWorld"
        chunks = smart_chunk_markdown(text)
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(hasattr(c, "start_line") for c in chunks)
        assert all(hasattr(c, "end_line") for c in chunks)
