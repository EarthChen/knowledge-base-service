"""Tests for architecture layer summary in domain compose."""

from __future__ import annotations

from wiki.nodes.domain_compose import _build_layer_summary


def test_build_layer_summary_basic() -> None:
    """Verify output format groups modules by layer."""
    module_names = ["UserController", "AuthHandler", "UserService", "AuthService", "UserRepo"]
    architecture_layers = {
        "UserController": {"layer": "api", "confidence": 0.9},
        "AuthHandler": {"layer": "api", "confidence": 0.85},
        "UserService": {"layer": "service", "confidence": 0.8},
        "AuthService": {"layer": "service", "confidence": 0.75},
        "UserRepo": {"layer": "data", "confidence": 0.7},
    }

    summary = _build_layer_summary(module_names, architecture_layers)

    assert summary.startswith("Architecture layers in this domain:")
    assert "- api (2 modules): UserController, AuthHandler" in summary
    assert "- service (2 modules): UserService, AuthService" in summary
    assert "- data (1 modules): UserRepo" in summary
    assert "infrastructure" not in summary


def test_build_layer_summary_empty() -> None:
    """No layers → empty string."""
    assert _build_layer_summary(["ModA"], {}) == ""
    assert _build_layer_summary([], {"ModA": {"layer": "api", "confidence": 0.9}}) == ""
