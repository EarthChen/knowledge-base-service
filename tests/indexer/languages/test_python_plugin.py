"""Tests for PythonPlugin."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages.python_lang import PythonPlugin


def _reverse_index(file_index: dict[str, str]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for path, mod in file_index.items():
        rev.setdefault(mod, []).append(path)
    return rev


def test_python_plugin_isinstance_and_properties() -> None:
    p = PythonPlugin()
    assert isinstance(p, LanguagePlugin)
    assert p.name == "python"
    assert p.file_extensions == [".py"]
    assert p.interop_group is None


def test_python_get_queries_keys() -> None:
    q = PythonPlugin().get_queries()
    assert set(q.keys()) == {"function", "class", "import", "call"}


def test_python_compute_fqn() -> None:
    p = PythonPlugin()
    fp = "proj/pkg/mod.py"
    assert p.compute_fqn(fp, "TopFn", "Function") == "proj.pkg.mod.TopFn"
    assert p.compute_fqn(fp, "C", "Class") == "proj.pkg.mod.C"
    assert p.compute_fqn(fp, "meth", "Function", parent_class="C") == "proj.pkg.mod.C.meth"


def test_python_build_module_name() -> None:
    p = PythonPlugin()
    assert p.build_module_name("a/b/c.py") == "a.b.c"
    assert p.build_module_name("pkg/__init__.py") == "pkg"


def test_python_resolve_import_absolute() -> None:
    p = PythonPlugin()
    fi = {"os/path.py": "os.path", "pkg/__init__.py": "pkg", "pkg/sub.py": "pkg.sub"}
    rev = _reverse_index(fi)
    assert p.resolve_import("os.path", "any.py", fi, rev) == "os/path.py"
    assert p.resolve_import("pkg.sub", "x.py", fi, rev) == "pkg/sub.py"


def test_python_resolve_import_relative() -> None:
    p = PythonPlugin()
    fi = {"pkg/a.py": "pkg.a", "pkg/b.py": "pkg.b", "pkg/__init__.py": "pkg"}
    rev = _reverse_index(fi)
    assert p.resolve_import(".b", "pkg/a.py", fi, rev) == "pkg/b.py"
