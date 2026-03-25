"""Tests for document indexer (Markdown/RST parsing)."""

import pytest

from indexer.doc_indexer import DocumentIndexer, DocumentSection, ParsedDocument
from store.schema import EdgeType, NodeLabel


@pytest.fixture
def indexer():
    return DocumentIndexer()


class TestMarkdownParsing:
    def test_parse_headings(self, indexer: DocumentIndexer):
        content = """# Title

Introduction text.

## Section One

Content of section one.

## Section Two

Content of section two.
"""
        doc = indexer.parse_document("README.md", content)

        assert doc.title == "Title"
        assert len(doc.sections) == 3  # Title + 2 sections

    def test_section_content(self, indexer: DocumentIndexer):
        content = """# My Doc

## Setup

Install dependencies with pip.
"""
        doc = indexer.parse_document("guide.md", content)

        setup_sections = [s for s in doc.sections if s.title == "Setup"]
        assert len(setup_sections) == 1
        assert "Install dependencies" in setup_sections[0].content

    def test_heading_levels(self, indexer: DocumentIndexer):
        content = """# H1

## H2

### H3
"""
        doc = indexer.parse_document("test.md", content)

        levels = [s.level for s in doc.sections]
        assert levels == [1, 2, 3]

    def test_content_hash(self, indexer: DocumentIndexer):
        doc1 = indexer.parse_document("a.md", "Hello")
        doc2 = indexer.parse_document("b.md", "Hello")
        doc3 = indexer.parse_document("c.md", "World")

        assert doc1.content_hash == doc2.content_hash
        assert doc1.content_hash != doc3.content_hash

    def test_empty_document(self, indexer: DocumentIndexer):
        doc = indexer.parse_document("empty.md", "")
        assert doc.sections == []
        assert doc.title == "empty"


class TestRSTParsing:
    def test_parse_rst_headings(self, indexer: DocumentIndexer):
        content = """Main Title
==========

Introduction text.

Sub Section
-----------

Sub content.
"""
        doc = indexer.parse_document("guide.rst", content)

        assert len(doc.sections) >= 2
        titles = [s.title for s in doc.sections]
        assert "Main Title" in titles
        assert "Sub Section" in titles

    def test_rst_heading_levels(self, indexer: DocumentIndexer):
        content = """Level 1
=======

Level 2
-------
"""
        doc = indexer.parse_document("test.rst", content)

        assert doc.sections[0].level < doc.sections[1].level


class TestCodeReferenceExtraction:
    def test_extract_inline_code_refs(self, indexer: DocumentIndexer):
        content = "Use `authenticate` to log in and `SessionRegistry` to manage sessions."
        doc = indexer.parse_document("doc.md", content)

        assert "authenticate" in doc.code_references
        assert "SessionRegistry" in doc.code_references

    def test_ignores_short_refs(self, indexer: DocumentIndexer):
        content = "Set `x` to `10`."
        doc = indexer.parse_document("doc.md", content)

        assert "x" not in doc.code_references

    def test_ignores_code_blocks(self, indexer: DocumentIndexer):
        content = """Text with `realRef`.

```python
not_a_ref = True
```

More text with `anotherRef`.
"""
        doc = indexer.parse_document("doc.md", content)

        assert "realRef" in doc.code_references
        assert "anotherRef" in doc.code_references
        assert "not_a_ref" not in doc.code_references

    def test_dotted_refs(self, indexer: DocumentIndexer):
        content = "Call `module.function_name` for setup."
        doc = indexer.parse_document("doc.md", content)

        assert "function_name" in doc.code_references


class TestGraphBuilding:
    def test_builds_document_node(self, indexer: DocumentIndexer):
        doc = indexer.parse_document("README.md", "# My Project\n\nIntro.")
        nodes, edges = indexer.build_graph(doc)

        doc_nodes = [n for n in nodes if n.label == NodeLabel.DOCUMENT]
        assert len(doc_nodes) >= 1
        assert doc_nodes[0].properties["title"] == "My Project"

    def test_builds_section_nodes(self, indexer: DocumentIndexer):
        content = "# Title\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        doc = indexer.parse_document("doc.md", content)
        nodes, edges = indexer.build_graph(doc)

        doc_nodes = [n for n in nodes if n.label == NodeLabel.DOCUMENT]
        assert len(doc_nodes) == 4  # 1 doc + 3 sections (title + A + B)

    def test_builds_contains_edges(self, indexer: DocumentIndexer):
        content = "# Title\n\n## Section\n\nContent."
        doc = indexer.parse_document("doc.md", content)
        nodes, edges = indexer.build_graph(doc)

        contains_edges = [e for e in edges if e.edge_type == EdgeType.CONTAINS]
        assert len(contains_edges) >= 1

    def test_builds_references_edges(self, indexer: DocumentIndexer):
        content = "# Guide\n\nUse `AuthService` for authentication."
        doc = indexer.parse_document("doc.md", content)
        nodes, edges = indexer.build_graph(doc)

        ref_edges = [e for e in edges if e.edge_type == EdgeType.REFERENCES]
        assert len(ref_edges) >= 1
