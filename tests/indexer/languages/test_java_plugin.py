"""Tests for JavaPlugin and JVM common helpers."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages._jvm_common import compute_jvm_fqn
from indexer.languages.java_lang import JavaPlugin


def _reverse_index(file_index: dict[str, str]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for path, mod in file_index.items():
        rev.setdefault(mod, []).append(path)
    return rev


def test_compute_jvm_fqn_kotlin_marker() -> None:
    """Kotlin roots participate in JVM FQN layout when markers are provided."""
    from indexer.languages._jvm_common import _ALL_JVM_SRC_MARKERS

    fp = "demo/src/main/kotlin/com/example/App.kt"
    assert compute_jvm_fqn(
        fp, "run", is_method=False, parent_class="", file_suffix=".kt",
        src_markers=_ALL_JVM_SRC_MARKERS,
    ) == "com.example.App"


def test_java_plugin_isinstance_and_properties() -> None:
    j = JavaPlugin()
    assert isinstance(j, LanguagePlugin)
    assert j.name == "java"
    assert j.file_extensions == [".java"]
    assert j.interop_group == "jvm"


def test_java_get_queries_keys() -> None:
    q = JavaPlugin().get_queries()
    assert set(q.keys()) == {"function", "class", "import", "call"}


def test_java_compute_fqn_class_and_method() -> None:
    j = JavaPlugin()
    fp = "svc/src/main/java/com/acme/Foo.java"
    assert j.compute_fqn(fp, "Foo", "Class") == "com.acme.Foo"
    assert j.compute_fqn(fp, "bar", "Function", parent_class="Foo") == "com.acme.Foo#bar"


def test_java_build_module_name() -> None:
    j = JavaPlugin()
    assert j.build_module_name("src/com/example/My.java") == "src.com.example.My"


def test_java_resolve_import() -> None:
    j = JavaPlugin()
    fi = {"src/com/example/Foo.java": "src.com.example.Foo"}
    rev = _reverse_index(fi)
    assert j.resolve_import("com.example.Foo", "x.java", fi, rev) == "src/com/example/Foo.java"
