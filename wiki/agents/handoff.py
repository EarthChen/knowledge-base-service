"""Handoff formalization for multi-agent delegation.

Provides typed HandoffConfig describing how one agent delegates to another,
with depth/count limiting and structured HandoffResult.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from core.log import get_logger
from wiki.agents.context import WikiDeps
from wiki.agents.delegation import DelegationConfig, DelegationMode, execute_delegation

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
    """Deprecated: use execute_delegation from wiki.agents.delegation instead."""
    warnings.warn(
        "execute_handoff is deprecated, use execute_delegation from wiki.agents.delegation",
        DeprecationWarning,
        stacklevel=2,
    )

    domain = domain_name or focus or ", ".join(entity_names[:3])
    deleg_config = DelegationConfig(
        mode=DelegationMode.ISOLATED,
        max_depth=config.max_depth,
        max_count=config.max_count,
        max_rounds=3,
    )

    factory = config.target_factory
    if baseline_context is not None:
        original_factory = config.target_factory

        def factory(child_deps):  # type: ignore[misc]
            agent = original_factory(child_deps)
            original_generate = agent.generate

            async def generate_with_baseline(**kwargs):
                bc = kwargs.get("baseline_context") or {}
                if isinstance(baseline_context, dict):
                    merged = {**bc, **baseline_context} if isinstance(bc, dict) else baseline_context
                    kwargs["baseline_context"] = merged
                else:
                    kwargs["baseline_context"] = baseline_context
                return await original_generate(**kwargs)

            agent.generate = generate_with_baseline
            return agent

    result = await execute_delegation(
        deleg_config,
        factory,
        deps,
        task_input={
            "module_names": entity_names,
            "domain_name": domain,
            "max_rounds": 3,
        },
    )

    metadata = dict(result.metadata)
    if not metadata.get("error"):
        metadata.setdefault("entity_names", entity_names)
        metadata.setdefault("focus", focus)

    return HandoffResult(
        output=result.output,
        metadata=metadata,
        tool_calls_made=result.tool_calls_made,
    )
