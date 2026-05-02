"""Structural protocols for WikiService dependency boundaries."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WikiGraphStorePort(Protocol):
    """Graph persistence backend: Cypher execution used by WikiService and snapshots."""

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any: ...
