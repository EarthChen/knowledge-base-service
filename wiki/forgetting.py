"""Ebbinghaus-style retention for knowledge pages (no destructive deletes)."""

from __future__ import annotations

import math

FADE_THRESHOLD = 0.3
ARCHIVE_THRESHOLD = 0.1
INITIAL_STABILITY = 7.0


def compute_retention(elapsed_days: float, stability: float) -> float:
    """Ebbinghaus forgetting curve: retention = e^(-t/S)"""
    if stability <= 0:
        return 0.0
    return math.exp(-elapsed_days / stability)


def update_stability(current_stability: float, multiplier: float = 1.5) -> float:
    """Increase stability on access/confirmation."""
    return current_stability * multiplier
