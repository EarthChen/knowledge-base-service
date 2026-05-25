"""FalkorDB queries for module call graph construction."""
from __future__ import annotations

import asyncio
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_MODULE_CALLS_CYPHER = (
    "MATCH (m1:Module)-[:CONTAINS*1..2]->(f1)"
    "-[:CALLS]->(f2)<-[:CONTAINS*1..2]-(m2:Module) "
    "WHERE (m1.repository + '|' + m1.name) IN $valid_pairs "
    "AND (m2.repository + '|' + m2.name) IN $valid_pairs "
    "AND m1 <> m2 "
    "RETURN m1.repository AS source_repo, m1.name AS source, "
    "m2.repository AS target_repo, m2.name AS target, "
    "count(*) AS weight"
)

_MODULE_DEPENDS_ON_CYPHER = (
    "MATCH (m1:Module)-[:CONTAINS*1..2]->(c1:Class)"
    "-[:DEPENDS_ON]->(c2:Class)<-[:CONTAINS*1..2]-(m2:Module) "
    "WHERE (m1.repository + '|' + m1.name) IN $valid_pairs "
    "AND (m2.repository + '|' + m2.name) IN $valid_pairs "
    "AND m1 <> m2 "
    "RETURN m1.repository AS source_repo, m1.name AS source, "
    "m2.repository AS target_repo, m2.name AS target, "
    "count(*) AS weight"
)

_QUERY_NAMES = {
    _MODULE_CALLS_CYPHER: "CALLS",
    _MODULE_DEPENDS_ON_CYPHER: "DEPENDS_ON",
}


async def fetch_module_call_edges(
    graph_store: Any,
    repositories: list[str],
    valid_modules: set[tuple[str, str]],
) -> tuple[list[tuple[tuple[str, str], tuple[str, str], int]], list[str]]:
    """Fetch weighted module call edges from FalkorDB (CALLS + DEPENDS_ON).

    Returns:
        Tuple of (edges, errors) where edges is a list of (source_node, target_node, weight)
        and errors is a list of error message strings for failed queries.
    """
    edge_map: dict[tuple[tuple[str, str], tuple[str, str]], int] = {}
    errors: list[str] = []
    valid_pairs = [f"{repo}|{name}" for repo, name in valid_modules]

    async def _run_query(cypher: str) -> None:
        query_name = _QUERY_NAMES.get(cypher, cypher[:40])
        try:
            result = await graph_store.execute_query(
                cypher, {"valid_pairs": valid_pairs}
            )
            for row in result.data:
                source_repo = row.get("source_repo")
                source = row.get("source")
                target_repo = row.get("target_repo")
                target = row.get("target")
                if not source_repo or not source or not target_repo or not target:
                    continue
                source_node = (str(source_repo), str(source))
                target_node = (str(target_repo), str(target))
                if source_node not in valid_modules or target_node not in valid_modules:
                    continue
                weight = int(row.get("weight", 0))
                key = (source_node, target_node)
                edge_map[key] = edge_map.get(key, 0) + weight
        except Exception as exc:
            log.warning("fetch_module_edges_query_failed", cypher=query_name, exc_info=True)
            errors.append(f"{query_name}: {exc}")

    await asyncio.gather(*[_run_query(c) for c in (_MODULE_CALLS_CYPHER, _MODULE_DEPENDS_ON_CYPHER)])

    return [(src, dst, w) for (src, dst), w in edge_map.items()], errors
