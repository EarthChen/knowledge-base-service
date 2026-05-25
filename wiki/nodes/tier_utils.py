"""Shared tier resolution for quality_gate and heal nodes."""
from __future__ import annotations

from wiki.models import ImportanceTier


def tier_for_module_count(module_count: int) -> str:
    """Map domain module count to importance tier string (for resolve_tier)."""
    if module_count >= 15:
        return "core"
    if module_count >= 2:
        return "standard"
    return "skeleton"


def resolve_tier(page_path: str, importance_tiers: dict[str, str]) -> ImportanceTier:
    """Resolve importance tier for a page, defaulting to CORE when tiers are empty."""
    if not importance_tiers:
        return ImportanceTier.CORE
    raw = str(importance_tiers.get(page_path, "")).lower()
    if raw == "skeleton":
        return ImportanceTier.SKELETON
    if raw == "standard":
        return ImportanceTier.STANDARD
    return ImportanceTier.CORE
