"""Tests for LanguagePlugin protocol and PluginRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from indexer.languages import LanguagePlugin, PluginRegistry
from indexer.tree_sitter_parser import ParsedField, ParsedImport, ParseResult

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


class _StubPlugin:
    """Minimal structural implementation of LanguagePlugin."""

    def __init__(
        self,
        name: str = "stub",
        file_extensions: list[str] | None = None,
        interop_group: str | None = None,
    ) -> None:
        self._name = name
        self._file_extensions = file_extensions or [".stub"]
        self._interop_group = interop_group

    @property
    def name(self) -> str:
        return self._name

    @property
    def file_extensions(self) -> list[str]:
        return list(self._file_extensions)

    @property
    def interop_group(self) -> str | None:
        return self._interop_group

    def get_queries(self) -> dict[str, str]:
        return {}

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        return []

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        return []

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        return ""

    def extract_signature(self, func_node: Node, source: bytes) -> str:
        return ""

    def accept_class_query_capture(self, class_node: Node, name_node: Node) -> bool:
        return True

    def extract_function_name_from_node(self, func_node: Node, source: bytes) -> str:
        return ""

    def extract_call_name_from_node(self, call_node: Node, source: bytes) -> str:
        return ""

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        return [], []

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]:
        return []

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        return ""

    def should_include_function(self, func_node: Node) -> bool:
        return True

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return ""

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return ""

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        return ""

    def extract_field_comments(self, class_node: Node, source: bytes) -> dict[str, str]:
        return {}

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        return []

    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        return ""

    def build_module_name(self, file_path: str) -> str:
        return ""

    def resolve_import(
        self,
        import_path: str,
        source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]],
    ) -> str | None:
        return None

    def extract_fields(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        result: ParseResult,
    ) -> list[ParsedField]:
        return []


def test_register_and_lookup_by_name() -> None:
    reg = PluginRegistry()
    p = _StubPlugin(name="alpha", file_extensions=[".a"])
    reg.register(p)
    assert reg.get_by_name("alpha") is p
    assert reg.get_by_name("missing") is None


def test_lookup_by_extension_normalized() -> None:
    reg = PluginRegistry()
    p = _StubPlugin(name="pyish", file_extensions=[".py"])
    reg.register(p)
    assert reg.get_by_extension(".py") is p
    assert reg.get_by_extension("py") is p


def test_interop_peers_same_group() -> None:
    reg = PluginRegistry()
    js = _StubPlugin(name="javascript", file_extensions=[".js"], interop_group="web")
    ts = _StubPlugin(name="typescript", file_extensions=[".ts"], interop_group="web")
    py = _StubPlugin(name="python", file_extensions=[".py"], interop_group=None)
    reg.register(js)
    reg.register(ts)
    reg.register(py)

    peers_js = reg.get_interop_peers(js)
    assert peers_js == [ts]

    peers_ts = reg.get_interop_peers(ts)
    assert peers_ts == [js]

    assert reg.get_interop_peers(py) == []


def test_supported_languages_sorted() -> None:
    reg = PluginRegistry()
    reg.register(_StubPlugin(name="zebra", file_extensions=[".z"]))
    reg.register(_StubPlugin(name="apple", file_extensions=[".a"]))
    assert reg.supported_languages == ["apple", "zebra"]


def test_file_extensions_property_per_language() -> None:
    reg = PluginRegistry()
    reg.register(_StubPlugin(name="one", file_extensions=[".z", ".y"]))
    reg.register(_StubPlugin(name="two", file_extensions=[".z", ".x"]))
    assert reg.file_extensions == {"one": [".z", ".y"], "two": [".z", ".x"]}


def test_runtime_check_isinstance_language_plugin() -> None:
    assert isinstance(_StubPlugin(), LanguagePlugin)


def test_duplicate_extension_first_wins() -> None:
    reg = PluginRegistry()
    first = _StubPlugin(name="first", file_extensions=[".dup"])
    second = _StubPlugin(name="second", file_extensions=[".dup"])
    reg.register(first)
    reg.register(second)
    assert reg.get_by_extension(".dup") is first


@pytest.mark.parametrize(
    ("stub", "expect_ok"),
    [
        (_StubPlugin(), True),
        (object(), False),
    ],
)
def test_protocol_runtime_check_negative(stub: object, expect_ok: bool) -> None:
    assert isinstance(stub, LanguagePlugin) is expect_ok
