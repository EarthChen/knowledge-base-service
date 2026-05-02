"""Shared list pagination helpers for REST routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Standard query pagination (optional on routes — callers may use ``limit=None`` for full lists)."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    """Generic envelope when an endpoint exposes explicit pages (optional pattern)."""

    items: list[Any] = Field(default_factory=list)
    total: int
    offset: int
    limit: int


def slice_page(items: list[Any], *, offset: int, limit: int | None) -> tuple[list[Any], int]:
    """Return ``(window, total)``. ``limit`` ``None`` means all items from ``offset`` (legacy full-list behavior)."""
    total = len(items)
    start = max(0, min(offset, total))
    if limit is None:
        return items[start:], total
    end = min(start + max(limit, 0), total)
    return items[start:end], total
