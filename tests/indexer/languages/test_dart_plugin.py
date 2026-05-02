"""Tests for DartPlugin."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages.dart_lang import DartPlugin


def _reverse_index(file_index: dict[str, str]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for path, mod in file_index.items():
        rev.setdefault(mod, []).append(path)
    return rev


def test_dart_plugin_isinstance_and_properties() -> None:
    d = DartPlugin()
    assert isinstance(d, LanguagePlugin)
    assert d.name == "dart"
    assert d.file_extensions == [".dart"]
    assert d.interop_group is None


def test_dart_get_queries_keys() -> None:
    q = DartPlugin().get_queries()
    assert set(q.keys()) == {"function", "class", "import", "call"}
    assert q["call"] == ""


def test_dart_compute_fqn_class_and_method() -> None:
    d = DartPlugin()
    fp = "lib/src/models/user.dart"
    assert d.compute_fqn(fp, "User", "Class") == "lib.src.models.user.User"
    assert d.compute_fqn(fp, "firstName", "Function", parent_class="User") == (
        "lib.src.models.user.User.firstName"
    )


def test_dart_build_module_name() -> None:
    d = DartPlugin()
    assert d.build_module_name("lib/src/models/user.dart") == "lib.src.models.user"


def test_dart_resolve_import_relative() -> None:
    d = DartPlugin()
    fi = {
        "lib/widgets/user.dart": "lib.widgets.user",
        "lib/features/home.dart": "lib.features.home",
    }
    rev = _reverse_index(fi)
    hit = d.resolve_import("../widgets/user.dart", "lib/features/home.dart", fi, rev)
    assert hit == "lib/widgets/user.dart"

