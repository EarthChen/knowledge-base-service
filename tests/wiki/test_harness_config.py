"""Tests for HarnessConfig."""
import os
import pytest


class TestHarnessConfig:
    def test_default_disabled(self):
        from wiki.agent_config import HarnessConfig
        config = HarnessConfig.from_env()
        assert config.enabled is False

    def test_enabled_from_env(self, monkeypatch):
        monkeypatch.setenv("WIKI__USE_HARNESS", "true")
        from wiki.agent_config import HarnessConfig
        config = HarnessConfig.from_env()
        assert config.enabled is True

    def test_custom_thresholds(self, monkeypatch):
        monkeypatch.setenv("WIKI__HARNESS_SIMPLE_THRESHOLD", "3")
        monkeypatch.setenv("WIKI__HARNESS_COMPLEX_THRESHOLD", "20")
        from wiki.agent_config import HarnessConfig
        config = HarnessConfig.from_env()
        assert config.simple_threshold == 3
        assert config.complex_threshold == 20
