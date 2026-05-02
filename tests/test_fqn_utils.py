"""Tests for store.fqn_utils — shared FQN regex and helpers."""
from __future__ import annotations

from store.fqn_utils import FQN_RE, extract_fqns, is_fqn, parse_fqn


class TestIsFqn:
    def test_valid_three_segment(self):
        assert is_fqn("com.example.MyClass") is True

    def test_valid_with_method(self):
        assert is_fqn("com.example.MyClass#doStuff") is True

    def test_valid_with_method_params(self):
        assert is_fqn("com.example.MyClass#doStuff(int, str)") is True

    def test_two_segments_rejected(self):
        assert is_fqn("example.MyClass") is False

    def test_simple_name_rejected(self):
        assert is_fqn("MyClass") is False

    def test_empty_rejected(self):
        assert is_fqn("") is False


class TestParseFqn:
    def test_simple_name_returns_none_fqn(self):
        fqn, simple = parse_fqn("MyClass")
        assert fqn == "MyClass"
        assert simple is None

    def test_fqn_returns_last_segment(self):
        fqn, simple = parse_fqn("com.example.MyClass")
        assert fqn == "com.example.MyClass"
        assert simple == "MyClass"

    def test_fqn_with_method_hash(self):
        fqn, simple = parse_fqn("com.example.MyClass#doStuff")
        assert fqn == "com.example.MyClass#doStuff"
        assert simple == "doStuff"


class TestExtractFqns:
    def test_extracts_from_text(self):
        text = "Call com.example.MyClass#run and org.foo.Bar.baz"
        result = extract_fqns(text)
        assert "com.example.MyClass#run" in result
        assert "org.foo.Bar.baz" in result

    def test_strips_params(self):
        text = "com.example.Foo#bar(int)"
        result = extract_fqns(text)
        assert result == ["com.example.Foo#bar"]

    def test_empty_text(self):
        assert extract_fqns("") == []
