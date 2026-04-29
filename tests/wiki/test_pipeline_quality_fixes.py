"""Tests for wiki content quality pipeline fixes."""

from __future__ import annotations

import inspect

import pytest

from wiki.service import WikiService


def test_generate_business_wiki_default_mode_is_full() -> None:
    sig = inspect.signature(WikiService.generate_business_wiki)
    mode_param = sig.parameters["mode"]
    assert mode_param.default == "full", (
        f"generate_business_wiki mode default should be 'full', got '{mode_param.default}'"
    )
