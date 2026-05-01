from __future__ import annotations

from config import AppWikiFlags


def test_semantic_group_flag_defaults():
    flags = AppWikiFlags()
    assert flags.code_structure_semantic_group is False
    assert flags.code_structure_semantic_group_threshold == 8


def test_semantic_group_flag_enabled():
    flags = AppWikiFlags(code_structure_semantic_group=True, code_structure_semantic_group_threshold=5)
    assert flags.code_structure_semantic_group is True
    assert flags.code_structure_semantic_group_threshold == 5
