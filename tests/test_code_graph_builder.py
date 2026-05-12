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


@pytest.fixture
def java_builder():
    parser = TreeSitterParser(supported_languages=["java"])
    return CodeGraphBuilder(parser=parser, file_extensions={"java": [".java"]})


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


class TestAnnotationAndSemanticRoles:
    def test_python_decorator_stored_in_node(self, builder: CodeGraphBuilder):
        code = '''@app.route("/")
def index():
    pass
'''
        nodes, _edges = builder.build_from_file("routes.py", content=code)
        func_nodes = [n for n in nodes if n.label == NodeLabel.FUNCTION and n.properties.get("name") == "index"]
        assert len(func_nodes) == 1
        anns = func_nodes[0].properties.get("annotations", [])
        assert any("app.route" in str(a) for a in anns)

    def test_semantic_roles_not_set_when_empty(self, builder: CodeGraphBuilder):
        code = "def plain():\n    pass\n"
        nodes, _edges = builder.build_from_file("plain.py", content=code)
        func_nodes = [n for n in nodes if n.label == NodeLabel.FUNCTION]
        assert len(func_nodes) == 1
        assert "semantic_roles" not in func_nodes[0].properties

    def test_type_info_stored_in_node(self, builder: CodeGraphBuilder):
        code = "def foo(x: int) -> str:\n    return str(x)\n"
        nodes, _edges = builder.build_from_file("typed.py", content=code)
        func_nodes = [n for n in nodes if n.label == NodeLabel.FUNCTION and n.properties.get("name") == "foo"]
        assert len(func_nodes) == 1
        props = func_nodes[0].properties
        assert props.get("return_type") == "str"
        assert props.get("parameters") == ["x:int"]


class TestGlobalSymbolTable:
    def test_builds_per_language_table(self, java_builder: CodeGraphBuilder):
        """Symbol table should have entries for classes and functions."""
        nodes_file1, _ = java_builder.build_from_file(
            "com/example/UserService.java",
            content="public class UserService {\n    public void save() {}\n}\n",
        )
        nodes_file2, _ = java_builder.build_from_file(
            "com/example/UserController.java",
            content="public class UserController {\n    public void create() {}\n}\n",
        )
        all_nodes = nodes_file1 + nodes_file2
        table = java_builder._build_global_symbol_table(all_nodes)

        assert "java" in table
        java_table = table["java"]
        # Should have entries for both class names
        found_names = list(java_table.keys())
        assert any("UserService" in k for k in found_names), f"UserService not found in {found_names}"
        assert any("UserController" in k for k in found_names), f"UserController not found in {found_names}"

    def test_fqn_takes_precedence(self, java_builder: CodeGraphBuilder):
        """When a node has fqn, that key should map to the node uid."""
        nodes, _ = java_builder.build_from_file(
            "com/example/UserService.java",
            content="public class UserService {}\n",
        )
        table = java_builder._build_global_symbol_table(nodes)
        java_table = table.get("java", {})
        class_nodes = [n for n in nodes if n.label == NodeLabel.CLASS]
        assert len(class_nodes) == 1
        # The class should be findable by its name
        assert "UserService" in java_table or any("UserService" in k for k in java_table)

    def test_python_functions_in_table(self, builder: CodeGraphBuilder):
        """Python functions should be in the python table."""
        nodes, _ = builder.build_from_file(
            "utils.py",
            content="def helper():\n    pass\n\ndef process():\n    pass\n",
        )
        table = builder._build_global_symbol_table(nodes)
        py_table = table.get("python", {})
        assert "helper" in py_table
        assert "process" in py_table

    def test_empty_nodes_returns_empty_tables(self, builder: CodeGraphBuilder):
        table = builder._build_global_symbol_table([])
        assert table == {}

    def test_module_nodes_excluded(self, builder: CodeGraphBuilder):
        """Module nodes should NOT be in the symbol table (only Class and Function)."""
        nodes, _ = builder.build_from_file("test.py", content="x = 1\n")
        table = builder._build_global_symbol_table(nodes)
        # Module node should not produce an entry
        py_table = table.get("python", {})
        # The module name "test" should not be in the table (it's a MODULE, not CLASS/FUNCTION)
        for key, uid in py_table.items():
            matching_nodes = [n for n in nodes if n.uid == uid]
            for n in matching_nodes:
                assert n.label != NodeLabel.MODULE


class TestModuleUIDUniqueness:
    def test_same_name_different_path_produces_different_uids(self, java_builder: CodeGraphBuilder):
        """Two Java files with the same name in different packages must have different Module UIDs."""
        code = "public class DeviceInfoDTO {}\n"
        nodes_a, _ = java_builder.build_from_file(
            "com/pkg/a/DeviceInfoDTO.java",
            content=code,
            store_path="com/pkg/a/DeviceInfoDTO.java",
        )
        nodes_b, _ = java_builder.build_from_file(
            "com/pkg/b/DeviceInfoDTO.java",
            content=code,
            store_path="com/pkg/b/DeviceInfoDTO.java",
        )
        mod_a = [n for n in nodes_a if n.label == NodeLabel.MODULE][0]
        mod_b = [n for n in nodes_b if n.label == NodeLabel.MODULE][0]
        assert mod_a.uid != mod_b.uid, (
            f"Same-name modules in different packages must have different UIDs: "
            f"{mod_a.uid} == {mod_b.uid}"
        )

    def test_module_uid_for_store_path_includes_path(self, java_builder: CodeGraphBuilder):
        """_module_uid_for_store_path should produce path-aware UIDs."""
        uid_a = java_builder._module_uid_for_store_path("com/pkg/a/Foo.java")
        uid_b = java_builder._module_uid_for_store_path("com/pkg/b/Foo.java")
        assert uid_a != uid_b, "Same filename in different paths should have different UIDs"

    def test_module_node_has_file_property(self, java_builder: CodeGraphBuilder):
        """Module node should have a 'file' property for UID generation."""
        code = "public class Foo {}\n"
        nodes, _ = java_builder.build_from_file(
            "com/example/Foo.java",
            content=code,
            store_path="com/example/Foo.java",
        )
        mod = [n for n in nodes if n.label == NodeLabel.MODULE][0]
        assert mod.properties.get("file") == "com/example/Foo.java", (
            f"Module should have file property, got: {mod.properties}"
        )


class TestIsTestFile:
    """Tests for CodeGraphBuilder.is_test_file static method."""

    # Java tests
    @pytest.mark.parametrize("path,lang", [
        ("com/example/FooTest.java", "java"),
        ("com/example/FooTests.java", "java"),
        ("com/example/FooIT.java", "java"),
        ("com/example/FooTestCase.java", "java"),
        ("src/test/java/com/example/Foo.java", "java"),
    ])
    def test_java_test_files_detected(self, path, lang):
        assert CodeGraphBuilder.is_test_file(path, lang) is True

    @pytest.mark.parametrize("path,lang", [
        ("com/example/FooService.java", "java"),
        ("com/example/TestUtils.java", "java"),
        ("com/example/Contest.java", "java"),
        ("src/main/java/com/example/Foo.java", "java"),
    ])
    def test_java_non_test_files_not_filtered(self, path, lang):
        assert CodeGraphBuilder.is_test_file(path, lang) is False

    # Kotlin tests
    @pytest.mark.parametrize("path,lang", [
        ("com/example/FooTest.kt", "kotlin"),
        ("src/test/kotlin/com/example/Foo.kt", "kotlin"),
    ])
    def test_kotlin_test_files_detected(self, path, lang):
        assert CodeGraphBuilder.is_test_file(path, lang) is True

    def test_kotlin_non_test_files(self):
        assert CodeGraphBuilder.is_test_file("com/example/FooService.kt", "kotlin") is False

    # Python tests
    @pytest.mark.parametrize("path,lang", [
        ("tests/test_foo.py", "python"),
        ("test_foo.py", "python"),
        ("foo_test.py", "python"),
        ("tests/conftest.py", "python"),
    ])
    def test_python_test_files_detected(self, path, lang):
        assert CodeGraphBuilder.is_test_file(path, lang) is True

    @pytest.mark.parametrize("path,lang", [
        ("src/foo.py", "python"),
        ("utils/contest.py", "python"),
        ("utils/testing_utils.py", "python"),
    ])
    def test_python_non_test_files_not_filtered(self, path, lang):
        assert CodeGraphBuilder.is_test_file(path, lang) is False

    # Go tests
    def test_go_test_file(self):
        assert CodeGraphBuilder.is_test_file("pkg/foo_test.go", "go") is True

    def test_go_non_test_file(self):
        assert CodeGraphBuilder.is_test_file("pkg/foo.go", "go") is False

    # JS/TS tests
    @pytest.mark.parametrize("path,lang", [
        ("src/foo.test.ts", "typescript"),
        ("src/foo.spec.ts", "typescript"),
        ("src/__tests__/foo.ts", "typescript"),
        ("src/foo.test.js", "javascript"),
        ("src/foo.spec.jsx", "javascript"),
    ])
    def test_js_ts_test_files_detected(self, path, lang):
        assert CodeGraphBuilder.is_test_file(path, lang) is True

    @pytest.mark.parametrize("path,lang", [
        ("src/foo.ts", "typescript"),
        ("src/utils.js", "javascript"),
    ])
    def test_js_ts_non_test_files(self, path, lang):
        assert CodeGraphBuilder.is_test_file(path, lang) is False

    # Swift tests
    def test_swift_test_file(self):
        assert CodeGraphBuilder.is_test_file("Tests/FooTests.swift", "swift") is True

    def test_swift_non_test_file(self):
        assert CodeGraphBuilder.is_test_file("Sources/Foo.swift", "swift") is False

    # Dart tests
    def test_dart_test_file(self):
        assert CodeGraphBuilder.is_test_file("test/foo_test.dart", "dart") is True

    def test_dart_non_test_file(self):
        assert CodeGraphBuilder.is_test_file("lib/foo.dart", "dart") is False

    # Unknown language / None
    def test_unknown_language_returns_false(self):
        assert CodeGraphBuilder.is_test_file("foo.xyz", None) is False

    def test_none_language_returns_false(self):
        assert CodeGraphBuilder.is_test_file("test_foo.py", None) is False
