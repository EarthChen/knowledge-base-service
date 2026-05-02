"""Tests for GoPlugin."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages.go_lang import GoPlugin


def _reverse_index(file_index: dict[str, str]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for path, mod in file_index.items():
        rev.setdefault(mod, []).append(path)
    return rev


def test_go_plugin_isinstance_and_properties() -> None:
    g = GoPlugin()
    assert isinstance(g, LanguagePlugin)
    assert g.name == "go"
    assert g.file_extensions == [".go"]
    assert g.interop_group is None


def test_go_get_queries_keys() -> None:
    q = GoPlugin().get_queries()
    assert set(q.keys()) == {"function", "class", "import", "call"}


def test_go_compute_fqn_struct_and_func() -> None:
    g = GoPlugin()
    fp = "handlers/api.go"
    pkg = "handlers"
    assert g.compute_fqn(fp, "User", "Class") == f"{pkg}.User"
    assert g.compute_fqn(fp, "Handle", "Function") == f"{pkg}.Handle"


def test_go_build_module_name() -> None:
    g = GoPlugin()
    assert g.build_module_name("internal/foo/bar.go") == "internal.foo.bar"


def test_go_resolve_import() -> None:
    g = GoPlugin()
    fi = {"vendor/acme/lib/widget.go": "vendor.acme.lib.widget"}
    rev = _reverse_index(fi)
    hit = g.resolve_import('"acme/lib"', "cmd/main.go", fi, rev)
    assert hit == "vendor/acme/lib/widget.go"
