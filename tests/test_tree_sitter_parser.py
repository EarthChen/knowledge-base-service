"""Tests for Tree-sitter multi-language AST parser."""

import pytest

from indexer.tree_sitter_parser import TreeSitterParser, ParseResult


@pytest.fixture
def parser():
    return TreeSitterParser(supported_languages=["python", "javascript"])


class TestPythonParsing:
    def test_parse_function(self, parser: TreeSitterParser):
        code = '''def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}"
'''
        result = parser.parse_file("test.py", "python", code)

        assert len(result.functions) == 1
        func = result.functions[0]
        assert func.name == "hello"
        assert func.file == "test.py"
        assert func.start_line == 1
        assert func.language == "python"
        assert "hello" in func.signature

    def test_parse_class(self, parser: TreeSitterParser):
        code = '''class Animal:
    """Base animal class."""
    def speak(self):
        pass
'''
        result = parser.parse_file("test.py", "python", code)

        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "Animal"
        assert cls.language == "python"

    def test_parse_class_with_inheritance(self, parser: TreeSitterParser):
        code = '''class Dog(Animal):
    def speak(self):
        return "Woof"
'''
        result = parser.parse_file("test.py", "python", code)

        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "Dog"
        assert "Animal" in cls.base_classes

    def test_parse_imports(self, parser: TreeSitterParser):
        code = '''import os
from pathlib import Path
'''
        result = parser.parse_file("test.py", "python", code)

        assert len(result.imports) >= 1
        modules = [imp.module for imp in result.imports]
        assert "os" in modules

    def test_parse_function_calls(self, parser: TreeSitterParser):
        code = '''def outer():
    inner()

def inner():
    pass
'''
        result = parser.parse_file("test.py", "python", code)

        assert len(result.functions) == 2
        assert len(result.calls) >= 1
        call = result.calls[0]
        assert call.caller_name == "outer"
        assert call.callee_name == "inner"

    def test_method_classified_under_class(self, parser: TreeSitterParser):
        code = '''class Foo:
    def bar(self):
        pass
'''
        result = parser.parse_file("test.py", "python", code)

        assert len(result.classes) == 1
        assert len(result.functions) == 1
        func = result.functions[0]
        assert func.parent_class == "Foo"
        assert len(result.classes[0].methods) == 1

    def test_empty_file(self, parser: TreeSitterParser):
        result = parser.parse_file("empty.py", "python", "")
        assert result.functions == []
        assert result.classes == []
        assert result.imports == []
        assert result.calls == []

    def test_code_snippet_truncation(self, parser: TreeSitterParser):
        long_body = "\n".join([f"    x_{i} = {i}" for i in range(500)])
        code = f"def big_func():\n{long_body}\n"
        result = parser.parse_file("test.py", "python", code)

        assert len(result.functions) == 1
        snip = result.functions[0].code_snippet
        assert "truncated" in snip
        assert len(snip) <= 3200
        assert "total chars" in snip

    def test_code_snippet_keeps_medium_methods_under_cap(self, parser: TreeSitterParser):
        body = "\n".join([f"    y_{i} = {i}" for i in range(80)])
        code = f"def medium():\n{body}\n"
        result = parser.parse_file("test.py", "python", code)
        assert len(result.functions) == 1
        snip = result.functions[0].code_snippet
        assert "truncated" not in snip
        assert len(snip) <= 5000

    def test_decorators(self, parser: TreeSitterParser):
        code = '''class Foo:
    @staticmethod
    def helper():
        pass
'''
        result = parser.parse_file("test.py", "python", code)

        helpers = [f for f in result.functions if f.name == "helper"]
        assert len(helpers) == 1


class TestJavaScriptParsing:
    def test_parse_function(self, parser: TreeSitterParser):
        code = '''function greet(name) {
    return "Hello, " + name;
}
'''
        result = parser.parse_file("test.js", "javascript", code)

        assert len(result.functions) == 1
        assert result.functions[0].name == "greet"
        assert result.functions[0].language == "javascript"

    def test_parse_class(self, parser: TreeSitterParser):
        code = '''class Person {
    constructor(name) {
        this.name = name;
    }
    greet() {
        return "Hello, " + this.name;
    }
}
'''
        result = parser.parse_file("test.js", "javascript", code)

        assert len(result.classes) == 1
        assert result.classes[0].name == "Person"


class TestUnsupportedLanguage:
    def test_unsupported_returns_empty(self, parser: TreeSitterParser):
        result = parser.parse_file("test.rb", "ruby", "puts 'hello'")
        assert result == ParseResult()

    def test_parse_file_returns_parse_result(self, parser: TreeSitterParser):
        result = parser.parse_file("test.py", "python", "x = 1")
        assert isinstance(result, ParseResult)


@pytest.fixture
def java_parser():
    return TreeSitterParser(supported_languages=["java"])


class TestJavaAnnotationExtraction:
    def test_java_marker_annotation(self, java_parser: TreeSitterParser):
        code = "@Service\npublic class UserService { }\n"
        result = java_parser.parse_file("UserService.java", "java", code)
        assert len(result.classes) == 1
        assert "@Service" in result.classes[0].decorators

    def test_java_annotation_with_args(self, java_parser: TreeSitterParser):
        code = '@RequestMapping("/api") public class Controller { }\n'
        result = java_parser.parse_file("Controller.java", "java", code)
        assert len(result.classes) == 1
        decs = result.classes[0].decorators
        assert any("@RequestMapping" in d and "/api" in d for d in decs)

    def test_java_method_annotation(self, java_parser: TreeSitterParser):
        code = """public class X {
    @GetMapping("/users")
    public void list() {}
}
"""
        result = java_parser.parse_file("X.java", "java", code)
        funcs = [f for f in result.functions if f.name == "list"]
        assert len(funcs) == 1
        assert any("@GetMapping" in d and "/users" in d for d in funcs[0].decorators)

    def test_java_multiple_annotations(self, java_parser: TreeSitterParser):
        code = "@MoaProvider @Service\npublic class Y { }\n"
        result = java_parser.parse_file("Y.java", "java", code)
        assert len(result.classes) == 1
        decs = result.classes[0].decorators
        assert "@MoaProvider" in decs and "@Service" in decs


class TestPythonDecoratorExtraction:
    def test_python_class_decorator(self, parser: TreeSitterParser):
        code = "@dataclass\nclass Foo:\n    pass\n"
        result = parser.parse_file("foo.py", "python", code)
        assert len(result.classes) == 1
        assert "@dataclass" in result.classes[0].decorators

    def test_python_function_decorator(self, parser: TreeSitterParser):
        code = """class Foo:
    @staticmethod
    def helper():
        pass
"""
        result = parser.parse_file("foo.py", "python", code)
        helpers = [f for f in result.functions if f.name == "helper"]
        assert len(helpers) == 1
        assert "@staticmethod" in helpers[0].decorators

    def test_python_multiple_decorators(self, parser: TreeSitterParser):
        code = '''@app.route("/")
@login_required
def index():
    pass
'''
        result = parser.parse_file("app.py", "python", code)
        funcs = [f for f in result.functions if f.name == "index"]
        assert len(funcs) == 1
        assert funcs[0].decorators == ['@app.route("/")', "@login_required"]


class TestTypeExtraction:
    def test_python_typed_parameters(self, parser: TreeSitterParser):
        code = """def foo(x: int, y: str) -> bool:
    return True
"""
        result = parser.parse_file("t.py", "python", code)
        f = result.functions[0]
        assert f.parameters == [{"name": "x", "type": "int"}, {"name": "y", "type": "str"}]
        assert f.return_type == "bool"

    def test_python_untyped_parameters(self, parser: TreeSitterParser):
        code = """def foo(x, y):
    pass
"""
        result = parser.parse_file("t.py", "python", code)
        assert result.functions[0].parameters == [
            {"name": "x", "type": ""},
            {"name": "y", "type": ""},
        ]

    def test_python_skip_self(self, parser: TreeSitterParser):
        code = """def foo(self, x: int):
    pass
"""
        result = parser.parse_file("t.py", "python", code)
        assert result.functions[0].parameters == [{"name": "x", "type": "int"}]

    def test_java_typed_parameters(self, java_parser: TreeSitterParser):
        code = """public class Demo {
    public void getUser(Long id, String name) {}
}
"""
        result = java_parser.parse_file("Demo.java", "java", code)
        f = next(f for f in result.functions if f.name == "getUser")
        assert f.parameters == [
            {"name": "id", "type": "Long"},
            {"name": "name", "type": "String"},
        ]

    def test_java_return_type(self, java_parser: TreeSitterParser):
        code = """import java.util.List;
public class Demo {
    public List<User> getUsers() { return null; }
}
"""
        result = java_parser.parse_file("Demo.java", "java", code)
        f = next(f for f in result.functions if f.name == "getUsers")
        assert f.return_type == "List<User>"
