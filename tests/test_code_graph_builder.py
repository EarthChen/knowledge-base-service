"""Tests for code graph builder (AST → Property Graph)."""

import pytest

from indexer.code_graph_builder import CodeGraphBuilder
from indexer.tree_sitter_parser import TreeSitterParser
from store.schema import EdgeType, NodeLabel


@pytest.fixture
def builder():
    parser = TreeSitterParser(supported_languages=["python", "javascript"])
    file_extensions = {
        "python": [".py"],
        "javascript": [".js"],
    }
    return CodeGraphBuilder(parser=parser, file_extensions=file_extensions)


class TestLanguageDetection:
    def test_detect_python(self, builder: CodeGraphBuilder):
        assert builder.detect_language("src/main.py") == "python"

    def test_detect_javascript(self, builder: CodeGraphBuilder):
        assert builder.detect_language("src/app.js") == "javascript"

    def test_detect_unknown(self, builder: CodeGraphBuilder):
        assert builder.detect_language("data.csv") is None

    def test_detect_no_extension(self, builder: CodeGraphBuilder):
        assert builder.detect_language("Makefile") is None


class TestBuildFromFile:
    def test_builds_module_node(self, builder: CodeGraphBuilder):
        code = "x = 1"
        nodes, edges = builder.build_from_file("src/utils.py", content=code)

        module_nodes = [n for n in nodes if n.label == NodeLabel.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].properties["name"] == "utils"
        assert module_nodes[0].properties["language"] == "python"

    def test_builds_function_node(self, builder: CodeGraphBuilder):
        code = "def hello():\n    pass\n"
        nodes, edges = builder.build_from_file("test.py", content=code)

        func_nodes = [n for n in nodes if n.label == NodeLabel.FUNCTION]
        assert len(func_nodes) == 1
        assert func_nodes[0].properties["name"] == "hello"

    def test_builds_class_node(self, builder: CodeGraphBuilder):
        code = "class Foo:\n    pass\n"
        nodes, edges = builder.build_from_file("test.py", content=code)

        class_nodes = [n for n in nodes if n.label == NodeLabel.CLASS]
        assert len(class_nodes) == 1
        assert class_nodes[0].properties["name"] == "Foo"

    def test_module_contains_function_edge(self, builder: CodeGraphBuilder):
        code = "def hello():\n    pass\n"
        nodes, edges = builder.build_from_file("test.py", content=code)

        contains_edges = [e for e in edges if e.edge_type == EdgeType.CONTAINS]
        assert len(contains_edges) >= 1

    def test_class_contains_method_edge(self, builder: CodeGraphBuilder):
        code = "class Foo:\n    def bar(self):\n        pass\n"
        nodes, edges = builder.build_from_file("test.py", content=code)

        contains_edges = [e for e in edges if e.edge_type == EdgeType.CONTAINS]
        assert len(contains_edges) >= 2

    def test_calls_edge(self, builder: CodeGraphBuilder):
        code = "def a():\n    b()\n\ndef b():\n    pass\n"
        nodes, edges = builder.build_from_file("test.py", content=code)

        call_edges = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(call_edges) >= 1

    def test_inheritance_edge(self, builder: CodeGraphBuilder):
        code = "class Base:\n    pass\n\nclass Child(Base):\n    pass\n"
        nodes, edges = builder.build_from_file("test.py", content=code)

        inherits_edges = [e for e in edges if e.edge_type == EdgeType.INHERITS]
        assert len(inherits_edges) >= 1

    def test_imports_edge(self, builder: CodeGraphBuilder):
        code = "import os\n"
        nodes, edges = builder.build_from_file("test.py", content=code)

        import_edges = [e for e in edges if e.edge_type == EdgeType.IMPORTS]
        assert len(import_edges) >= 1

    def test_unsupported_file_returns_empty(self, builder: CodeGraphBuilder):
        nodes, edges = builder.build_from_file("data.csv", content="a,b,c")
        assert nodes == []
        assert edges == []

    def test_javascript_file(self, builder: CodeGraphBuilder):
        code = "function greet() { return 'hello'; }\n"
        nodes, edges = builder.build_from_file("app.js", content=code)

        func_nodes = [n for n in nodes if n.label == NodeLabel.FUNCTION]
        assert len(func_nodes) == 1
        assert func_nodes[0].properties["language"] == "javascript"
