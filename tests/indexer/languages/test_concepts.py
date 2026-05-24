"""Tests for language-specific concept lists on LanguagePlugins."""

from __future__ import annotations

import pytest

from indexer.languages import create_default_registry
from indexer.languages._base import BaseLanguagePlugin
from indexer.languages.python_lang import PythonPlugin


def test_base_plugin_concepts_default() -> None:
    """Base class should expose concepts as an empty list by default."""
    assert BaseLanguagePlugin.concepts.fget is not None
    plugin = PythonPlugin()
    assert isinstance(plugin.concepts, list)


@pytest.mark.parametrize(
    "plugin_name",
    ["python", "java", "go", "kotlin", "javascript", "swift", "dart", "objc"],
)
def test_plugin_has_concepts(plugin_name: str) -> None:
    """Each language plugin should define at least 5 concepts."""
    registry = create_default_registry()
    plugin = registry.get_by_name(plugin_name)
    assert plugin is not None, f"Plugin {plugin_name} not registered"
    assert len(plugin.concepts) >= 5, f"{plugin_name} should have ≥5 concepts"
    assert all(isinstance(c, str) and c.strip() for c in plugin.concepts)
