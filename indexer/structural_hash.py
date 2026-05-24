"""Structural hash for API-surface change detection (COSMETIC vs STRUCTURAL)."""

from __future__ import annotations

import hashlib
from enum import StrEnum

from store.schema import GraphEdge, GraphNode


class ChangeLevel(StrEnum):
    NONE = "none"
    COSMETIC = "cosmetic"
    STRUCTURAL = "structural"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prop_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    return str(value)


def compute_structural_hash(
    functions: list[GraphNode],
    classes: list[GraphNode],
    imports: list[GraphEdge],
) -> str:
    """Hash function signatures, class declarations, and imports (ignores docstrings/bodies)."""
    parts: list[str] = []

    for fn in sorted(functions, key=lambda n: str(n.properties.get("name", ""))):
        name = _prop_str(fn.properties.get("name", ""))
        signature = _prop_str(fn.properties.get("signature", ""))
        parameters = _prop_str(fn.properties.get("parameters", ""))
        return_type = _prop_str(fn.properties.get("return_type", ""))
        parts.append(f"fn:{name}|{signature}|{parameters}|{return_type}")

    for cls in sorted(classes, key=lambda n: str(n.properties.get("name", ""))):
        name = _prop_str(cls.properties.get("name", ""))
        base_classes = _prop_str(cls.properties.get("base_classes", ""))
        interfaces = _prop_str(cls.properties.get("interfaces", ""))
        parts.append(f"cls:{name}|{base_classes}|{interfaces}")

    for imp in sorted(imports, key=lambda e: e.target_uid):
        parts.append(f"imp:{imp.target_uid}")

    return _sha256_hex("|".join(parts))
