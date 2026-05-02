"""Tests for JavaScriptPlugin and TypeScriptPlugin."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages.javascript_lang import JavaScriptPlugin, TypeScriptPlugin


def _reverse_index(file_index: dict[str, str]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for path, mod in file_index.items():
        rev.setdefault(mod, []).append(path)
    return rev


def test_js_plugin_isinstance_and_properties() -> None:
    js = JavaScriptPlugin()
    assert isinstance(js, LanguagePlugin)
    assert js.name == "javascript"
    assert js.file_extensions == [".js", ".jsx", ".mjs"]
    assert js.interop_group == "js"


def test_ts_plugin_isinstance_and_properties() -> None:
    ts = TypeScriptPlugin()
    assert isinstance(ts, LanguagePlugin)
    assert ts.name == "typescript"
    assert ts.file_extensions == [".ts", ".tsx"]
    assert ts.interop_group == "js"


def test_js_ts_get_queries_class_diff() -> None:
    js_q = JavaScriptPlugin().get_queries()["class"]
    ts_q = TypeScriptPlugin().get_queries()["class"]
    assert "identifier" in js_q and "type_identifier" in ts_q
    assert js_q != ts_q
    assert set(JavaScriptPlugin().get_queries().keys()) == {"function", "class", "import", "call"}
    assert set(TypeScriptPlugin().get_queries().keys()) == {"function", "class", "import", "call"}


def test_js_compute_fqn() -> None:
    js = JavaScriptPlugin()
    fp = "src/components/Button.tsx"
    assert js.compute_fqn(fp, "Button", "Class") == "src/components/Button.Button"


def test_js_build_module_name_regular_and_index() -> None:
    js = JavaScriptPlugin()
    assert js.build_module_name("routes/admin/settings.ts") == "routes.admin.settings"
    assert js.build_module_name("routes/admin/index.ts") == "routes.admin"


def test_js_resolve_import_relative() -> None:
    js = JavaScriptPlugin()
    fi = {"pkg/ui.tsx": "pkg.ui"}
    rev = _reverse_index(fi)
    assert js.resolve_import("./ui", "pkg/page.tsx", fi, rev) == "pkg/ui.tsx"


def test_ts_inherits_resolve_and_fqn_pattern() -> None:
    ts = TypeScriptPlugin()
    fp = "lib/util.ts"
    assert ts.compute_fqn(fp, "help", "Function") == "lib/util.help"
