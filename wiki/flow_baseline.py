"""Structural baseline extraction for business flow documentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

ENTRY_POINT_CY = """
MATCH (m:Module)-[:CONTAINS]->(f:Function)
WHERE (
    (size($valid_pairs) > 0 AND (m.repository + '|' + m.name) IN $valid_pairs)
    OR (size($bare_names) > 0 AND m.name IN $bare_names)
)
AND (
    ANY(a IN coalesce(f.annotations, []) WHERE
        a CONTAINS 'RequestMapping'
        OR a CONTAINS 'PostMapping'
        OR a CONTAINS 'GetMapping'
        OR a CONTAINS 'PutMapping'
        OR a CONTAINS 'DeleteMapping'
        OR a CONTAINS 'PatchMapping'
        OR a CONTAINS 'app.route'
        OR a CONTAINS 'router.'
        OR a CONTAINS 'KafkaListener'
        OR a CONTAINS 'KafkaHandler'
        OR a CONTAINS 'EventListener'
        OR a CONTAINS 'Scheduled'
        OR a CONTAINS 'GrpcService'
    )
    OR 'http_endpoint' IN coalesce(f.semantic_roles, [])
    OR 'message_listener' IN coalesce(f.semantic_roles, [])
    OR 'scheduled_task' IN coalesce(f.semantic_roles, [])
    OR 'rpc_provider' IN coalesce(f.semantic_roles, [])
    OR f.name = 'main'
)
RETURN f.name AS name, m.name AS module, f.file_path AS file_path, f.annotations AS annotations
LIMIT 50
"""

CROSS_DOMAIN_CY = """
MATCH (m1:Module)-[:CONTAINS]->(f1:Function)-[:CALLS]->(f2:Function)<-[:CONTAINS]-(m2:Module)
WHERE (
    (size($valid_pairs) > 0 AND (m1.repository + '|' + m1.name) IN $valid_pairs)
    OR (size($bare_names) > 0 AND m1.name IN $bare_names)
)
AND NOT (
    (size($valid_pairs) > 0 AND (m2.repository + '|' + m2.name) IN $valid_pairs)
    OR (size($bare_names) > 0 AND m2.name IN $bare_names)
)
RETURN DISTINCT m1.name AS src_module, m2.name AS tgt_module
LIMIT 20
"""


@dataclass
class EntryPointInfo:
    function_name: str
    module_name: str
    entry_type: str
    file_path: str


@dataclass
class FlowBaseline:
    domain_name: str
    entry_points: list[EntryPointInfo] = field(default_factory=list)
    call_chains: list[Any] = field(default_factory=list)
    module_count: int = 0
    cross_domain_calls: list[tuple[str, str]] = field(default_factory=list)


def _split_module_pairs(pairs: list[str]) -> tuple[list[str], list[str]]:
    """Split compound repo|name keys from bare module names for query scoping."""
    compound = [p for p in pairs if "|" in p]
    bare = [p for p in pairs if "|" not in p]
    return compound, bare


def _classify_entry_type(annotations: str | list[str] | None) -> str:
    if annotations is None:
        ann = ""
    elif isinstance(annotations, list):
        ann = " ".join(str(a) for a in annotations).lower()
    else:
        ann = str(annotations).lower()
    http_keys = (
        "requestmapping", "postmapping", "getmapping", "putmapping",
        "deletemapping", "app.route", "router.",
    )
    if any(k in ann for k in http_keys):
        return "http"
    if any(k in ann for k in ("grpcservice",)):
        return "rpc"
    if any(k in ann for k in ("kafkalistener", "eventlistener")):
        return "event"
    if "scheduled" in ann:
        return "scheduled"
    return "main"


async def extract_flow_baseline(
    graph_store: Any,
    domain_name: str,
    module_names: list[str] | None = None,
    *,
    valid_pairs: list[str] | None = None,
) -> FlowBaseline:
    """Extract structural baseline from graph for FlowDocAgent pre-fill."""
    entry_points: list[EntryPointInfo] = []
    call_chains: list[Any] = []
    cross_domain_calls: list[tuple[str, str]] = []

    pairs = valid_pairs if valid_pairs is not None else (module_names or [])
    chain_modules = module_names or [p.split("|", 1)[-1] for p in pairs if "|" in p] or list(pairs)
    compound_pairs, bare_names = _split_module_pairs(pairs)
    query_params = {"valid_pairs": compound_pairs, "bare_names": bare_names}

    try:
        result = await graph_store.execute_query(ENTRY_POINT_CY, query_params)
        for row in getattr(result, "data", None) or []:
            if not isinstance(row, dict):
                continue
            ep = EntryPointInfo(
                function_name=str(row.get("name", "")),
                module_name=str(row.get("module", "")),
                entry_type=_classify_entry_type(row.get("annotations")),
                file_path=str(row.get("file_path", "")),
            )
            entry_points.append(ep)
    except Exception:
        log.warning("flow_baseline_entry_points_failed", domain=domain_name, exc_info=True)

    try:
        from wiki.call_chain_builder import CallChainBuilder

        builder = CallChainBuilder(graph_store)
        call_chains = await builder.build_chains(chain_modules, max_depth=5, max_chains=15)
    except Exception:
        log.warning("flow_baseline_call_chains_failed", domain=domain_name, exc_info=True)

    try:
        result = await graph_store.execute_query(CROSS_DOMAIN_CY, query_params)
        for row in getattr(result, "data", None) or []:
            if isinstance(row, dict):
                cross_domain_calls.append((str(row.get("src_module", "")), str(row.get("tgt_module", ""))))
    except Exception:
        log.warning("flow_baseline_cross_domain_failed", domain=domain_name, exc_info=True)

    return FlowBaseline(
        domain_name=domain_name,
        entry_points=entry_points,
        call_chains=call_chains,
        module_count=len(pairs),
        cross_domain_calls=cross_domain_calls,
    )


def format_flow_baseline_for_prompt(baseline: FlowBaseline) -> str:
    """Format baseline for injection into agent system prompt."""
    if not baseline.entry_points and not baseline.call_chains and not baseline.cross_domain_calls:
        return ""
    lines: list[str] = []
    if baseline.entry_points:
        lines.append("Entry points:")
        for ep in baseline.entry_points:
            lines.append(f"  [{ep.entry_type}] {ep.module_name}.{ep.function_name}")
    if baseline.call_chains:
        lines.append("Main call chains available (see agent tools for details)")
    if baseline.cross_domain_calls:
        lines.append("Cross-domain calls:")
        for src, tgt in baseline.cross_domain_calls:
            lines.append(f"  {src} → {tgt}")
    return "\n".join(lines)
