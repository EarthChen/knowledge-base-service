from unittest.mock import MagicMock

from wiki.composer import WikiComposer
from wiki.data_collector import PageData
from wiki.models import CodeSnippet, ImportanceTier, PageType, SourceLocation
from store.schema import GraphNode, NodeLabel


def _make_page_data_with_code() -> PageData:
    node = GraphNode(
        label=NodeLabel.CLASS,
        uid="Class:f.py:Foo:1",
        properties={
            "name": "Foo",
            "file": "src/foo.py",
            "start_line": 1,
            "end_line": 50,
            "signature": "class Foo:",
        },
    )
    return PageData(
        node=node,
        edges=[],
        children=[],
        source_location=SourceLocation(
            file_path="src/foo.py",
            start_line=1,
            end_line=50,
            fqn="Foo",
            repository="repo",
        ),
        method_locations=[],
        business_summary=None,
        methods=[],
        code_snippets=[
            CodeSnippet(
                source="class Foo:\n    def bar(self):\n        return 42",
                file_path="src/foo.py",
                start_line=1,
                end_line=3,
                origin="chunk",
            ),
        ],
        importance_tier=ImportanceTier.CORE,
    )


def test_entity_digest_includes_code():
    composer = WikiComposer(llm=None, context_builder=MagicMock(), store=MagicMock())
    page_data = _make_page_data_with_code()
    digest = composer._entity_digest(page_data, page_type=PageType.CLASS_DETAIL)
    assert "class Foo:" in digest
    assert "def bar" in digest
