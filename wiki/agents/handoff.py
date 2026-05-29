"""Handoff formalization for multi-agent delegation.

Provides typed HandoffConfig describing how one agent delegates to another,
with depth/count limiting and structured HandoffResult.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from core.log import get_logger
from wiki.agents.context import WikiDeps

log = get_logger(__name__)


@dataclass
class HandoffConfig:
    """Defines how one agent can hand off to another."""

    target_factory: Callable[[WikiDeps], Any]
    tool_name: str = ""
    description: str = ""
    input_type: type[BaseModel] | None = None
    input_filter: Callable[[list[dict]], list[dict]] | None = None
    max_depth: int = 2
    max_count: int = 3


class DelegateInput(BaseModel):
    """Default input type for submodule delegation."""

    entity_names: list[str]
    focus: str = ""


@dataclass
class HandoffResult:
    """Result of a handoff execution."""

    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls_made: int = 0


async def execute_handoff(
    config: HandoffConfig,
    deps: WikiDeps,
    *,
    entity_names: list[str],
    focus: str = "",
    domain_name: str = "",
    baseline_context: Any = None,
) -> HandoffResult:
    """Execute a handoff with depth/count validation.

    Creates a child agent via config.target_factory with incremented
    delegation_depth. Returns HandoffResult.
    """
    if deps.delegation_depth >= config.max_depth:
        return HandoffResult(
            output="",
            metadata={"error": f"max delegation depth reached: {deps.delegation_depth}"},
        )
    if deps.delegation_count >= config.max_count:
        return HandoffResult(
            output="",
            metadata={"error": f"max delegation count reached: {deps.delegation_count}"},
        )

    child_deps = dataclasses.replace(
        deps,
        delegation_depth=deps.delegation_depth + 1,
        delegation_count=deps.delegation_count + 1,  # D-06: increment, not reset
    )

    try:
        child_agent = config.target_factory(child_deps)
        domain = domain_name or focus or ", ".join(entity_names[:3])
        output = await child_agent.generate(
            module_names=entity_names,
            domain_name=domain,
            baseline_context=baseline_context or {},
            max_rounds=3,
        )
        return HandoffResult(output=output, metadata={"entity_names": entity_names, "focus": focus})
    except Exception as e:
        log.warning("handoff_execution_failed", entities=entity_names, error=str(e))
        return HandoffResult(output="", metadata={"error": str(e)})
