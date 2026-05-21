"""FalkorDB queries for module call graph construction."""
from __future__ import annotations

from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_MODULE_CALLS_CYPHER = (
    "MATCH (m1:Module)-[:CONTAINS*1..3]->(f1)"
    "-[:CALLS]->(f2)<-[:CONTAINS*1..3]-(m2:Module) "
    "WHERE m1.repository IN $repos AND m2.repository IN $repos AND m1 <> m2 "
    "RETURN m1.repository AS source_repo, m1.name AS source, "
    "m2.repository AS target_repo, m2.name AS target, "
    "count(*) AS weight"
)

_MODULE_DEPENDS_ON_CYPHER = (
    "MATCH (m1:Module)-[:CONTAINS*1..3]->(c1:Class)"
    "-[:DEPENDS_ON]->(c2:Class)<-[:CONTAINS*1..3]-(m2:Module) "
    "WHERE m1.repository IN $repos AND m2.repository IN $repos AND m1 <> m2 "
    "RETURN m1.repository AS source_repo, m1.name AS source, "
    "m2.repository AS target_repo, m2.name AS target, "
    "count(*) AS weight"
)


async def fetch_module_call_edges(
    graph_store: Any,
    repositories: list[str],
    valid_modules: set[tuple[str, str]],
) -> list[tuple[tuple[str, str], tuple[str, str], int]]:
    """Fetch weighted module call edges from FalkorDB (CALLS + DEPENDS_ON).

    Returns:
        List of (source_node, target_node, weight) where nodes are (repo_id, module_name) tuples.
    """
    edge_map: dict[tuple[tuple[str, str], tuple[str, str]], int] = {}

    for cypher in (_MODULE_CALLS_CYPHER, _MODULE_DEPENDS_ON_CYPHER):
        try:
            result = await graph_store.execute_query(cypher, {"repos": repositories})
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
        except Exception:
            log.warning("fetch_module_edges_query_failed", cypher=cypher[:40], exc_info=True)

    return [(src, dst, w) for (src, dst), w in edge_map.items()]
