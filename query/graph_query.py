"""Graph query interface — parameterized Cypher templates for code analysis.

Provides pre-built Cypher query templates for common code analysis tasks:
call chains, inheritance trees, module dependencies, and entity lookups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from log import get_logger
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*)?"
)


def _parse_input(raw: str) -> tuple[str, str | None]:
    """Parse user input which may be a simple name or FQN.

    Returns (simple_name, fqn_or_none).
    For ``com.foo.Bar#doStuff`` returns (``doStuff``, ``com.foo.Bar#doStuff``).
    For ``com.foo.Bar`` returns (``Bar``, ``com.foo.Bar``).
    For ``loginV2`` returns (``loginV2``, None).
    """
    if _FQN_RE.fullmatch(raw.strip()):
        fqn = raw.strip()
        if "#" in fqn:
            simple = fqn.rsplit("#", 1)[1]
        else:
            simple = fqn.rsplit(".", 1)[-1]
        return simple, fqn
    return raw.strip(), None


def _make_params(raw: str) -> dict[str, str]:
    """Build query params with both fqn and simple_name for fallback matching."""
    simple, fqn = _parse_input(raw)
    return {"fqn": fqn or simple, "simple_name": simple}


def _where_name(alias: str) -> str:
    """Build a WHERE clause that tries fqn first, then falls back to simple name."""
    return f"({alias}.fqn = $fqn OR {alias}.name = $simple_name)"


@dataclass
class QueryResult:
    data: list[dict[str, Any]]
    query: str
    params: dict[str, Any]


class GraphQueryService:
    """Provides parameterized Cypher graph queries over the code knowledge graph."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def find_call_chain(
        self, function_name: str, depth: int = 3, direction: str = "downstream",
    ) -> QueryResult:
        """Find the call chain starting from a function.

        Accepts simple name (``loginV2``) or FQN (``com.foo.Bar#loginV2``).
        Returns nodes and edges for multi-level visualization.
        """
        params = _make_params(function_name)
        where = _where_name("f")

        if direction == "upstream":
            query = (
                f"MATCH (f:Function) WHERE {where} "
                "WITH f "
                f"MATCH path = (caller:Function)-[:CALLS*1..{depth}]->(f) "
                "UNWIND relationships(path) AS rel "
                "WITH startNode(rel) AS src, endNode(rel) AS tgt "
                "RETURN DISTINCT src.name AS src_name, src.file AS src_file, src.start_line AS src_line, "
                "coalesce(src.fqn, '') AS src_fqn, "
                "tgt.name AS tgt_name, tgt.file AS tgt_file, tgt.start_line AS tgt_line, "
                "coalesce(tgt.fqn, '') AS tgt_fqn"
            )
        else:
            query = (
                f"MATCH (f:Function) WHERE {where} "
                "WITH f "
                f"MATCH path = (f)-[:CALLS*1..{depth}]->(callee:Function) "
                "UNWIND relationships(path) AS rel "
                "WITH startNode(rel) AS src, endNode(rel) AS tgt "
                "RETURN DISTINCT src.name AS src_name, src.file AS src_file, src.start_line AS src_line, "
                "coalesce(src.fqn, '') AS src_fqn, "
                "tgt.name AS tgt_name, tgt.file AS tgt_file, tgt.start_line AS tgt_line, "
                "coalesce(tgt.fqn, '') AS tgt_fqn"
            )
        rows = await self._store.execute_query(query, params)

        nodes_map: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []

        for r in rows.data:
            src_key = f"{r.get('src_name', '')}:{r.get('src_line', 0)}"
            tgt_key = f"{r.get('tgt_name', '')}:{r.get('tgt_line', 0)}"
            if src_key not in nodes_map:
                nodes_map[src_key] = {
                    "name": r.get("src_name", ""),
                    "file": r.get("src_file", ""),
                    "line": r.get("src_line", 0),
                    "fqn": r.get("src_fqn", ""),
                }
            if tgt_key not in nodes_map:
                nodes_map[tgt_key] = {
                    "name": r.get("tgt_name", ""),
                    "file": r.get("tgt_file", ""),
                    "line": r.get("tgt_line", 0),
                    "fqn": r.get("tgt_fqn", ""),
                }
            edges.append({"source": src_key, "target": tgt_key})

        data = list(nodes_map.values())
        return QueryResult(
            data=data,
            query=query,
            params={**params, "_edges": edges},
        )

    async def find_inheritance_tree(self, class_name: str, direction: str = "children") -> QueryResult:
        """Find inheritance hierarchy for a class.

        Accepts simple name or FQN.
        """
        params = _make_params(class_name)
        where = _where_name("c")

        if direction == "parents":
            query = (
                f"MATCH (c:Class) WHERE {where} "
                "WITH c "
                "MATCH (c)-[:INHERITS*1..10]->(parent:Class) "
                "RETURN parent.name AS name, parent.file AS file, parent.start_line AS line"
            )
        else:
            query = (
                f"MATCH (c:Class) WHERE {where} "
                "WITH c "
                "MATCH (child:Class)-[:INHERITS*1..10]->(c) "
                "RETURN child.name AS name, child.file AS file, child.start_line AS line"
            )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "file": r[1], "line": r[2]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_class_methods(self, class_name: str) -> QueryResult:
        """Find all methods belonging to a class. Accepts simple name or FQN."""
        params = _make_params(class_name)
        where = _where_name("c")

        query = (
            f"MATCH (c:Class) WHERE {where} "
            "WITH c "
            "MATCH (c)-[:CONTAINS]->(m:Function) "
            "RETURN m.name AS name, m.signature AS signature, m.file AS file, m.start_line AS line "
            "ORDER BY m.start_line"
        )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "signature": r[1], "file": r[2], "line": r[3]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_module_dependencies(self, module_name: str) -> QueryResult:
        """Find what a module imports."""
        params = _make_params(module_name)
        where = _where_name("m")

        query = (
            f"MATCH (m:Module) WHERE {where} "
            "WITH m "
            "MATCH (m)-[:IMPORTS]->(dep:Module) "
            "RETURN dep.name AS name, dep.path AS path"
        )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_reverse_dependencies(self, module_name: str) -> QueryResult:
        """Find what modules import this module."""
        params = _make_params(module_name)
        where = _where_name("dep")

        query = (
            f"MATCH (dep:Module) WHERE {where} "
            "WITH dep "
            "MATCH (m:Module)-[:IMPORTS]->(dep) "
            "RETURN m.name AS name, m.path AS path"
        )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_entity(self, name: str, entity_type: str = "any") -> QueryResult:
        """Find a code entity by name or FQN."""
        params = _make_params(name)
        where = _where_name("n")

        if entity_type == "function":
            query = (
                f"MATCH (n:Function) WHERE {where} "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "n.signature AS signature, n.docstring AS docstring, 'Function' AS type"
            )
        elif entity_type == "class":
            query = (
                f"MATCH (n:Class) WHERE {where} "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "'' AS signature, n.docstring AS docstring, 'Class' AS type"
            )
        else:
            query = (
                "MATCH (n) "
                f"WHERE (n:Function OR n:Class OR n:Module) AND {where} "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "coalesce(n.signature, '') AS signature, "
                "coalesce(n.docstring, '') AS docstring, labels(n)[0] AS type"
            )
        rows = await self._store.execute_query(query, params)
        data = [
            {"name": r[0], "file": r[1], "line": r[2], "signature": r[3], "docstring": r[4], "type": r[5]}
            for r in rows
        ]
        return QueryResult(data=data, query=query, params=params)

    async def find_file_entities(self, file_path: str) -> QueryResult:
        """Find all entities defined in a file."""
        query = (
            "MATCH (n {file: $file}) "
            "WHERE n:Function OR n:Class "
            "RETURN n.name AS name, labels(n)[0] AS type, n.start_line AS line, "
            "coalesce(n.signature, '') AS signature "
            "ORDER BY n.start_line"
        )
        params = {"file": file_path}
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "type": r[1], "line": r[2], "signature": r[3]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def execute_raw(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Execute a raw Cypher query."""
        rows = await self._store.execute_query(cypher, params)
        data = [{"row": list(r)} for r in rows]
        return QueryResult(data=data, query=cypher, params=params or {})

    async def get_graph_stats(self) -> dict[str, int]:
        """Get statistics about the knowledge graph."""
        stats: dict[str, int] = {}
        for label in ("Function", "Class", "Module", "Document"):
            rows = await self._store.execute_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            stats[label.lower() + "_count"] = rows[0][0] if rows else 0

        for edge_type in ("CALLS", "INHERITS", "IMPORTS", "CONTAINS", "REFERENCES"):
            rows = await self._store.execute_query(f"MATCH ()-[r:{edge_type}]->() RETURN count(r) AS cnt")
            stats[edge_type.lower() + "_count"] = rows[0][0] if rows else 0

        return stats

    async def find_business_flow(self, name: str, k: int = 10) -> QueryResult:
        """Find a business flow and its implementing functions/classes."""
        query = (
            "MATCH (bf:BusinessFlow)-[r:IMPLEMENTS]->(n) "
            "WHERE bf.name CONTAINS $name "
            "RETURN bf, r, n ORDER BY r.step_order LIMIT $k"
        )
        params = {"name": name, "k": k}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def find_flows_for_function(self, function_name: str) -> QueryResult:
        """Reverse lookup: find business flows that a function belongs to."""
        params = _make_params(function_name)
        where = _where_name("f")
        query = (
            f"MATCH (bf:BusinessFlow)-[:IMPLEMENTS]->(f:Function) "
            f"WHERE {where} RETURN bf, f"
        )
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def find_related_concepts(self, entity_name: str) -> QueryResult:
        """Find business concepts related to a given entity."""
        query = (
            "MATCH (bc:BusinessConcept)-[r:RELATES_TO]->(n) "
            "WHERE n.name = $name "
            "RETURN bc, r, n ORDER BY r.relevance_score DESC"
        )
        params = {"name": entity_name}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def explore_business_domain(self, category: str) -> QueryResult:
        """Explore all flows and concepts in a business domain."""
        query = (
            "MATCH (bf:BusinessFlow) WHERE bf.category = $category "
            "OPTIONAL MATCH (bf)-[:IMPLEMENTS]->(f) "
            "RETURN bf, collect(f) AS functions"
        )
        params = {"category": category}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def find_flow_dependencies(self, flow_name: str) -> QueryResult:
        """Find parent/child flow relationships."""
        query = (
            "MATCH path=(bf:BusinessFlow)-[:PART_OF*0..3]->(parent:BusinessFlow) "
            "WHERE bf.name CONTAINS $name "
            "RETURN bf, parent, length(path) AS depth ORDER BY depth"
        )
        params = {"name": flow_name}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)
