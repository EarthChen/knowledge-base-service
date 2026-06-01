"""Tests for domain module signature computation."""
from __future__ import annotations

import pytest


def test_signature_stable_for_same_modules():
    from wiki.persistence import compute_domain_module_signature

    mods = [("repo", "B"), ("repo", "A")]
    assert compute_domain_module_signature(mods) == compute_domain_module_signature(list(reversed(mods)))


def test_signature_changes_when_modules_differ():
    from wiki.persistence import compute_domain_module_signature

    a = compute_domain_module_signature([("r", "A")])
    b = compute_domain_module_signature([("r", "A"), ("r", "B")])
    assert a != b


def test_signature_is_hex_string():
    from wiki.persistence import compute_domain_module_signature

    sig = compute_domain_module_signature([("repo", "Module")])
    assert len(sig) == 64  # SHA256 hex digest is 64 chars
    assert all(c in "0123456789abcdef" for c in sig)


def test_empty_modules_produces_valid_hash():
    from wiki.persistence import compute_domain_module_signature

    sig = compute_domain_module_signature([])
    assert len(sig) == 64
