from __future__ import annotations

import pytest


def test_iterative_rag_enabled_flag_removed():
    from core.config import AppWikiFlags

    flags = AppWikiFlags()
    assert not hasattr(flags, "iterative_rag_enabled")
