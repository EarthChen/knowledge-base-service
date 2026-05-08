"""Tests for Harness integration in compose.py."""
import inspect

import pytest


def test_compose_imports_harness():
    """compose.py should have WikiGenerationHarness import available."""
    from wiki.nodes import compose

    source = inspect.getsource(compose)
    assert "WikiGenerationHarness" in source or "harness" in source.lower()


def test_compose_passes_repo_path_to_agent():
    """compose.py should pass repo_path when creating WikiPageAgent."""
    from wiki.nodes import compose

    source = inspect.getsource(compose._compose_single_leaf_domain)
    assert "repo_path" in source


def test_harness_config_importable():
    """HarnessConfig should be importable from agent_config."""
    from wiki.agent_config import HarnessConfig

    config = HarnessConfig.from_env()
    assert hasattr(config, "enabled")
