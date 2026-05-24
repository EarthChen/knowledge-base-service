"""Structural baseline extraction for business flow documentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

ENTRY_POINT_CY = """
MATCH (m:Module)-[:CONTAINS]->(f:Function)
WHERE m.name IN $modules
AND (
    f.annotations CONTAINS 'RequestMapping'
    OR f.annotations CONTAINS 'PostMapping'
    OR f.annotations CONTAINS 'GetMapping'
    OR f.annotations CONTAINS 'PutMapping'
    OR f.annotations CONTAINS 'DeleteMapping'
    OR f.annotations CONTAINS 'app.route'
    OR f.annotations CONTAINS 'router.'
    OR f.annotations CONTAINS 'KafkaListener'
    OR f.annotations CONTAINS 'EventListener'
    OR f.annotations CONTAINS 'Scheduled'
    OR f.annotations CONTAINS 'GrpcService'
    OR f.name = 'main'
)
RETURN f.name AS name, m.name AS module, f.file_path AS file_path, f.annotations AS annotations
LIMIT 50
"""

CROSS_DOMAIN_CY = """
MATCH (m1:Module)-[:CONTAINS]->(f1:Function)-[:CALLS]->(f2:Function)<-[:CONTAINS]-(m2:Module)
WHERE m1.name IN $modules AND NOT m2.name IN $modules
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


def _classify_entry_type(annotations: str) -> str:
    ann = (annotations or "").lower()
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
    module_names: list[str],
) -> FlowBaseline:
    """Extract structural baseline from graph for FlowDocAgent pre-fill."""
    entry_points: list[EntryPointInfo] = []
    call_chains: list[Any] = []
    cross_domain_calls: list[tuple[str, str]] = []

    try:
        result = await graph_store.execute_query(ENTRY_POINT_CY, {"modules": module_names})
        for row in getattr(result, "data", None) or []:
            if not isinstance(row, dict):
                continue
            ep = EntryPointInfo(
                function_name=str(row.get("name", "")),
                module_name=str(row.get("module", "")),
                entry_type=_classify_entry_type(str(row.get("annotations", ""))),
                file_path=str(row.get("file_path", "")),
            )
            entry_points.append(ep)
    except Exception:
        log.warning("flow_baseline_entry_points_failed", domain=domain_name, exc_info=True)

    try:
        from wiki.call_chain_builder import CallChainBuilder

        builder = CallChainBuilder(graph_store)
        call_chains = await builder.build_chains(module_names, max_depth=5, max_chains=15)
    except Exception:
        log.warning("flow_baseline_call_chains_failed", domain=domain_name, exc_info=True)

    try:
        result = await graph_store.execute_query(CROSS_DOMAIN_CY, {"modules": module_names})
        for row in getattr(result, "data", None) or []:
            if isinstance(row, dict):
                cross_domain_calls.append((str(row.get("src_module", "")), str(row.get("tgt_module", ""))))
    except Exception:
        log.warning("flow_baseline_cross_domain_failed", domain=domain_name, exc_info=True)

    return FlowBaseline(
        domain_name=domain_name,
        entry_points=entry_points,
        call_chains=call_chains,
        module_count=len(module_names),
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
