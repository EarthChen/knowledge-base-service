"""Tests for SwiftPlugin."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages.swift_lang import SwiftPlugin


def test_swift_plugin_isinstance_and_properties() -> None:
    s = SwiftPlugin()
    assert isinstance(s, LanguagePlugin)
    assert s.name == "swift"
    assert s.file_extensions == [".swift"]
    assert s.interop_group == "apple"


def test_swift_get_queries_keys() -> None:
    q = SwiftPlugin().get_queries()
    assert set(q.keys()) == {"function", "class", "import", "call"}


def test_swift_compute_fqn_class_and_method() -> None:
    s = SwiftPlugin()
    fp = "Sources/MyApp/Models/User.swift"
    assert s.compute_fqn(fp, "Profile", "Class") == "Sources.MyApp.Models.User.Profile"
    assert s.compute_fqn(fp, "greet", "Function", parent_class="Profile") == "Sources.MyApp.Models.User.Profile.greet"


def test_swift_build_module_name() -> None:
    s = SwiftPlugin()
    assert s.build_module_name("Sources/MyApp/Models/User.swift") == "Sources.MyApp.Models.User"
