"""Tests for document graph building with smart markdown chunking."""

from indexer.doc_indexer import DocumentIndexer, ParsedDocument, DocumentSection
from indexer.smart_chunker import smart_chunk_markdown
from store.schema import NodeLabel


def _long_paragraph(min_chars: int = 2500) -> str:
    """Paragraphs separated by blank lines so smart_chunker can split."""
    para = ("Lorem ipsum dolor sit amet. " * 12).strip()
    parts: list[str] = []
    body = ""
    while len(body) < min_chars:
        parts.append(para)
        body = "\n\n".join(parts)
    return body


class TestDocIndexerChunking:
    def test_long_section_uses_smart_chunker_multiple_nodes(self) -> None:
        indexer = DocumentIndexer()
        body = _long_paragraph(2500)
        doc = ParsedDocument(
            title="BigDoc",
            path="big.md",
            sections=[
                DocumentSection(
                    title="Huge",
                    content=body,
                    level=2,
                    start_line=5,
                    end_line=200,
                ),
            ],
            content_hash="abc",
            code_references=[],
        )
        nodes, _edges = indexer.build_graph(doc)
        section_nodes = [
            n
            for n in nodes
            if n.label == NodeLabel.DOCUMENT and "section" in n.properties
        ]
        ref_chunks = smart_chunk_markdown(body, target_chars=2000)
        assert len(ref_chunks) >= 2
        assert len(section_nodes) == len(ref_chunks)
        for n in section_nodes:
            assert n.properties["content"] in body

    def test_short_section_single_node(self) -> None:
        indexer = DocumentIndexer()
        short = "Short section body."
        doc = ParsedDocument(
            title="Small",
            path="small.md",
            sections=[
                DocumentSection(
                    title="Intro",
                    content=short,
                    level=2,
                    start_line=3,
                    end_line=10,
                ),
            ],
            content_hash="def",
            code_references=[],
        )
        nodes, _ = indexer.build_graph(doc)
        section_nodes = [
            n
            for n in nodes
            if n.label == NodeLabel.DOCUMENT and "section" in n.properties
        ]
        assert len(section_nodes) == 1
        assert section_nodes[0].properties["content"] == short

    def test_code_block_not_split_across_chunks(self) -> None:
        indexer = DocumentIndexer()
        filler = _long_paragraph(1200)
        code_block = "```python\n" + "\n".join(f"x = {i}" for i in range(80)) + "\n```"
        body = f"{filler}\n\n{code_block}\n\n{filler}"
        doc = ParsedDocument(
            title="CodeDoc",
            path="code.md",
            sections=[
                DocumentSection(
                    title="WithCode",
                    content=body,
                    level=2,
                    start_line=1,
                    end_line=500,
                ),
            ],
            content_hash="ghi",
            code_references=[],
        )
        nodes, _ = indexer.build_graph(doc)
        section_nodes = [
            n
            for n in nodes
            if n.label == NodeLabel.DOCUMENT and "section" in n.properties
        ]
        for n in section_nodes:
            t = n.properties["content"]
            fc = t.count("```")
            assert fc % 2 == 0, f"unbalanced fences in chunk: {fc}"

    def test_each_chunk_has_heading_context_metadata(self) -> None:
        indexer = DocumentIndexer()
        body = _long_paragraph(2500)
        doc = ParsedDocument(
            title="Meta",
            path="meta.md",
            sections=[
                DocumentSection(
                    title="Chunked",
                    content=f"## Inner\n\n{body}",
                    level=2,
                    start_line=1,
                    end_line=300,
                ),
            ],
            content_hash="jkl",
            code_references=[],
        )
        nodes, _ = indexer.build_graph(doc)
        section_nodes = [
            n
            for n in nodes
            if n.label == NodeLabel.DOCUMENT and "section" in n.properties
        ]
        assert section_nodes
        for n in section_nodes:
            assert "heading_context" in n.properties
