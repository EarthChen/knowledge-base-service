from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ScopeType = Literal["page", "business", "repository", "global"]


@dataclass
class Chunk:
    content: str
    source: str
    title: str
    relevance: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Source:
    """Citation / provenance for SSE and final answer."""

    kind: Literal["wiki", "code", "graph", "graph_cypher"]
    title: str
    path: str
    relevance: float
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalScope:
    scope_type: ScopeType
    page_path: str | None = None
    business_id: str | None = None
    repository: str | None = None


class Retriever(Protocol):
    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]: ...
