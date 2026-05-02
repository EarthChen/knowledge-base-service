"""Tests for KotlinPlugin."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages.kotlin_lang import KotlinPlugin


def _reverse_index(file_index: dict[str, str]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for path, mod in file_index.items():
        rev.setdefault(mod, []).append(path)
    return rev


def test_kotlin_plugin_isinstance_and_properties() -> None:
    k = KotlinPlugin()
    assert isinstance(k, LanguagePlugin)
    assert k.name == "kotlin"
    assert k.file_extensions == [".kt", ".kts"]
    assert k.interop_group == "jvm"


def test_kotlin_get_queries_keys() -> None:
    q = KotlinPlugin().get_queries()
    assert set(q.keys()) == {"function", "class", "import", "call"}


def test_kotlin_compute_fqn_class_and_method() -> None:
    k = KotlinPlugin()
    fp = "svc/src/main/kotlin/com/acme/Foo.kt"
    assert k.compute_fqn(fp, "Foo", "Class") == "com.acme.Foo"
    assert k.compute_fqn(fp, "bar", "Function", parent_class="Foo") == "com.acme.Foo#bar"


def test_kotlin_build_module_name() -> None:
    k = KotlinPlugin()
    assert k.build_module_name("src/com/example/My.kt") == "src.com.example.My"


def test_kotlin_resolve_import_prefers_kt_then_java() -> None:
    k = KotlinPlugin()
    kt_path = "src/com/example/KFoo.kt"
    java_path = "src/com/example/JFoo.kt"
    fi = {
        kt_path: "src.com.example.KFoo",
        java_path: "src.com.example.JFoo",
    }
    rev = _reverse_index(fi)
    assert k.resolve_import("com.example.KFoo", "Main.kt", fi, rev) == kt_path
    assert k.resolve_import("com.example.JFoo", "Main.kt", fi, rev) == java_path


def test_kotlin_resolve_import_reverse_fallback() -> None:
    k = KotlinPlugin()
    fi: dict[str, str] = {}
    rev = {"com.misc.Lib": ["weird/layout/Lib.kt"]}
    assert k.resolve_import("com.misc.Lib", "x/Main.kt", fi, rev) == "weird/layout/Lib.kt"
