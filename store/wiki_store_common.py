"""Shared types and helpers for wiki store modules."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from store.falkordb_store import QueryResultWrapper
from store.schema import EdgeType, NodeLabel

SOURCE_DOC_EDGE = EdgeType.SOURCE_DOC.value


@runtime_checkable
class _GraphQueryPort(Protocol):
    """Any store or port that can run Cypher (FalkorDBStore, test doubles, etc.)."""

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any: ...


def wiki_node_properties(raw: object) -> dict[str, Any]:
    if raw is None:
        return {}
    if hasattr(raw, "properties"):
        return dict(raw.properties)  # type: ignore[arg-type]
    if isinstance(raw, dict):
        return raw
    return {}


# Backward compat with prior private name
_wiki_node_properties = wiki_node_properties
