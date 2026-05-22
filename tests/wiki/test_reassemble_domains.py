# tests/wiki/test_reassemble_domains.py
"""Tests for wiki-driven domain reassembly."""
from __future__ import annotations

import pytest


class TestReassemblyConfig:
    def test_default_config_values(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert flags.domain_reassembly_enabled is True
        assert flags.reassembly_merge_threshold == 0.85
        assert flags.reassembly_orphan_threshold == 0.60
        assert flags.reassembly_max_moves_pct == 0.30
        assert flags.reassembly_respect_user_modified is True

    def test_config_override(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags(
            domain_reassembly_enabled=False,
            reassembly_merge_threshold=0.9,
        )
        assert flags.domain_reassembly_enabled is False
        assert flags.reassembly_merge_threshold == 0.9


class TestPipelineState:
    def test_state_has_reassembly_actions_field(self):
        from wiki.pipeline_state import WikiPipelineState

        annotations = WikiPipelineState.__annotations__
        assert "reassembly_actions" in annotations

    def test_state_has_domain_display_names_field(self):
        from wiki.pipeline_state import WikiPipelineState

        annotations = WikiPipelineState.__annotations__
        assert "domain_display_names" in annotations
