from unittest.mock import MagicMock
from wiki.composer import WikiComposer
from wiki.data_collector import PageData
from wiki.models import ChunkSnippet, SourceLocation, PageType
from store.schema import GraphNode, NodeLabel


def _make_page_data_with_rag() -> PageData:
    node = GraphNode(
        label=NodeLabel.CLASS, uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py",
                    "start_line": 1, "end_line": 50, "signature": "class Foo:"},
    )
    return PageData(
        node=node, edges=[], children=[],
        source_location=SourceLocation(
            file_path="src/foo.py", start_line=1, end_line=50, fqn="Foo", repository="repo"),
        method_locations=[], business_summary=None, methods=[],
        related_chunks=[ChunkSnippet(
            text="class Bar:\n    def use_foo(self): Foo().run()",
            file_path="src/bar.py", score=0.85,
            parent_name="Bar", parent_uid="Class:bar.py:Bar:1",
            start_line=1, end_line=2,
        )],
    )


def test_entity_digest_includes_related_chunks():
    composer = WikiComposer(llm=None, context_builder=MagicMock(), store=MagicMock())
    page_data = _make_page_data_with_rag()
    digest = composer._entity_digest(page_data, page_type=PageType.CLASS_DETAIL)
    assert "Related Code" in digest
    assert "Bar" in digest
    assert "use_foo" in digest


def test_entity_digest_without_related_chunks():
    composer = WikiComposer(llm=None, context_builder=MagicMock(), store=MagicMock())
    node = GraphNode(
        label=NodeLabel.CLASS, uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py", "start_line": 1, "end_line": 50},
    )
    page_data = PageData(
        node=node, edges=[], children=[],
        source_location=SourceLocation(
            file_path="src/foo.py", start_line=1, end_line=50, fqn="Foo", repository="repo"),
        method_locations=[], business_summary=None, methods=[],
    )
    digest = composer._entity_digest(page_data, page_type=PageType.CLASS_DETAIL)
    assert "Related Code" not in digest
