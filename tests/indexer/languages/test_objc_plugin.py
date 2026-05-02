"""Tests for ObjectiveCPlugin."""

from __future__ import annotations

from indexer.languages import LanguagePlugin
from indexer.languages.objc_lang import ObjectiveCPlugin


def test_objc_plugin_isinstance_and_properties() -> None:
    o = ObjectiveCPlugin()
    assert isinstance(o, LanguagePlugin)
    assert o.name == "objc"
    assert o.file_extensions == [".m", ".h"]
    assert o.interop_group == "apple"


def test_objc_get_queries_keys() -> None:
    q = ObjectiveCPlugin().get_queries()
    assert set(q.keys()) == {"function", "class", "import", "call"}


def test_objc_compute_fqn_class_and_method() -> None:
    o = ObjectiveCPlugin()
    fp = "ios/MyProject/Sources/AppDelegate.m"
    assert o.compute_fqn(fp, "AppDelegate", "Class") == "AppDelegate"
    assert o.compute_fqn(fp, "viewDidLoad", "Function", parent_class="AppDelegate") == (
        "AppDelegate.viewDidLoad"
    )
    assert o.compute_fqn(fp, "plainC", "Function", parent_class="") == (
        "ios.MyProject.Sources.AppDelegate.plainC"
    )


def test_objc_build_module_name() -> None:
    o = ObjectiveCPlugin()
    assert o.build_module_name("ios/src/Foo.m") == "ios.src.Foo"
