"""Typed dependency injection context for agent tool loops.

RunContext carries dependencies (graph store, search service, etc.)
that tools need at runtime. It is NOT sent to the LLM — only to
tool handlers, guardrails, and hooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class RunContext(Generic[T]):
    """Typed DI context threaded through tool dispatch."""
    deps: T
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WikiDeps:
    """Wiki-agent-specific dependencies."""
    graph_store: Any
    search_service: Any | None = None
    repo_path: str | None = None
    business_id: str = ""
    existing_pages: list[dict] | None = None
    delegation_depth: int = 0
    delegation_count: int = 0
