from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.log import get_logger

log = get_logger(__name__)


class DelegationMode(Enum):
    ISOLATED = "isolated"
    SEEDED = "seeded"
    FULL = "full"


_READ_ONLY_TOOLS = frozenset({
    "search_entities",
    "read_code",
    "query_call_chain",
    "query_callers",
    "query_implementations",
    "read_file",
    "semantic_search",
    "grep_code",
    "list_files",
    "list_domains",
    "read_wiki_page",
})


@dataclass
class DelegationConfig:
    mode: DelegationMode = DelegationMode.SEEDED
    max_depth: int = 2
    max_count: int = 3
    max_rounds: int = 3
    allowed_tools: list[str] | None = None
    read_only: bool = False
    seed_memory_fields: list[str] = field(
        default_factory=lambda: [
            "code_snippets",
            "discovered_call_chains",
            "search_findings",
            "relevant_modules",
            "facts",
        ]
    )
    result_schema: type | None = None


@dataclass
class DelegationResult:
    output: str = ""
    memory_summary: str = ""
    quality_score: float = 0.0
    covered_entities: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    tool_calls_made: int = 0
    delegation_depth: int = 0
    child_memory: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


async def execute_delegation(
    config: DelegationConfig,
    factory: Callable,
    deps: Any,
    *,
    task_input: dict[str, Any],
    parent_memory: Any | None = None,
    message_history: list[dict] | None = None,
    domain_name: str = "",
) -> DelegationResult:
    if deps.delegation_depth >= config.max_depth:
        return DelegationResult(metadata={"error": "max_depth"})
    if deps.delegation_count >= config.max_count:
        return DelegationResult(metadata={"error": "max_count"})

    if dataclasses.is_dataclass(deps) and not isinstance(deps, type):
        child_deps = dataclasses.replace(
            deps,
            delegation_depth=deps.delegation_depth + 1,
            delegation_count=deps.delegation_count + 1,
        )
    else:
        child_deps = copy.copy(deps)
        child_deps.delegation_depth = deps.delegation_depth + 1
        child_deps.delegation_count = deps.delegation_count + 1

    baseline: dict = {}
    if config.mode == DelegationMode.SEEDED and parent_memory:
        seed = parent_memory.slice(set(config.seed_memory_fields))
        baseline = {"memory_seed": seed.to_prompt(max_chars=8000)}
    elif config.mode == DelegationMode.FULL and message_history:
        baseline = {"message_history": message_history}

    child_agent = factory(child_deps)
    if config.read_only:
        if hasattr(child_agent, "restrict_tools"):
            child_agent.restrict_tools(config.allowed_tools or list(_READ_ONLY_TOOLS))
    elif config.allowed_tools:
        if hasattr(child_agent, "restrict_tools"):
            child_agent.restrict_tools(config.allowed_tools)

    try:
        output = await child_agent.generate(**task_input, baseline_context=baseline)
    except Exception as e:
        log.error("delegation_failed", error=str(e))
        return DelegationResult(metadata={"error": str(e)})

    child_mem = getattr(child_agent, "_current_memory", None)
    return DelegationResult(
        output=str(output),
        memory_summary=_summarize_memory(child_mem),
        quality_score=_estimate_quality(child_mem, output),
        covered_entities=_extract_entities(child_mem),
        gaps=_extract_gaps(child_mem),
        tool_calls_made=getattr(child_agent, "_tool_call_count", 0),
        delegation_depth=child_deps.delegation_depth,
        child_memory=child_mem,
    )


def _summarize_memory(mem: Any) -> str:
    if mem is None:
        return ""
    if hasattr(mem, "to_prompt"):
        return mem.to_prompt(max_chars=2000)
    return str(mem)[:2000]


def _estimate_quality(mem: Any, output: Any) -> float:
    if not output or str(output).strip() == "":
        return 0.0
    score = 0.5
    if mem and hasattr(mem, "code_snippets") and mem.code_snippets:
        score += 0.2
    if mem and hasattr(mem, "discovered_call_chains") and mem.discovered_call_chains:
        score += 0.2
    if mem and hasattr(mem, "relevant_modules") and mem.relevant_modules:
        score += 0.1
    return min(score, 1.0)


def _extract_entities(mem: Any) -> list[str]:
    if mem and hasattr(mem, "relevant_modules"):
        return list(mem.relevant_modules or [])
    return []


def _extract_gaps(mem: Any) -> list[str]:
    if mem and hasattr(mem, "context_gaps"):
        return list(mem.context_gaps or [])
    return []
