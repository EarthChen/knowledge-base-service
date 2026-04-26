"""Tests for wiki.forgetting (Ebbinghaus retention)."""

from __future__ import annotations

import math
from math import exp

import pytest

from wiki.forgetting import (
    ARCHIVE_THRESHOLD,
    FADE_THRESHOLD,
    INITIAL_STABILITY,
    compute_retention,
    update_stability,
)


def test_retention_at_t_equals_zero() -> None:
    assert abs(compute_retention(0.0, 7.0) - 1.0) < 1e-9


def test_retention_zero_stability() -> None:
    assert compute_retention(1.0, 0.0) == 0.0
    assert compute_retention(0.0, 0.0) == 0.0


def test_retention_matches_formula() -> None:
    t, s = 7.0, 7.0
    expected = exp(-t / s)
    assert abs(compute_retention(t, s) - expected) < 1e-12


@pytest.mark.parametrize(
    ("elapsed", "stability", "expected"),
    [
        (1.0, 7.0, math.exp(-1.0 / 7.0)),
        (7.0, 7.0, math.exp(-1.0)),
        (14.0, 7.0, math.exp(-2.0)),
    ],
)
def test_retention_parametrized(
    elapsed: float,
    stability: float,
    expected: float,
) -> None:
    assert abs(compute_retention(elapsed, stability) - expected) < 1e-9


def test_update_stability_default_multiplier() -> None:
    assert update_stability(4.0) == 6.0


@pytest.mark.parametrize(
    ("current", "mult", "out"),
    [
        (1.0, 1.5, 1.5),
        (7.0, 2.0, 14.0),
    ],
)
def test_update_stability_parametrized(current: float, mult: float, out: float) -> None:
    assert update_stability(current, multiplier=mult) == out


def test_module_constants() -> None:
    assert FADE_THRESHOLD == 0.3
    assert ARCHIVE_THRESHOLD == 0.1
    assert INITIAL_STABILITY == 7.0
