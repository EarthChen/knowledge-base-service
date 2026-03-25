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
        assert len(result.functions[0].code_snippet) <= 2020

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
