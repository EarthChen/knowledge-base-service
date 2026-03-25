"""Graph query interface — parameterized Cypher templates for code analysis.

Provides pre-built Cypher query templates for common code analysis tasks:
call chains, inheritance trees, module dependencies, and entity lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from log import get_logger

from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


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

        direction: "downstream" = who does this function call
                   "upstream"   = who calls this function
        """
        if direction == "upstream":
            query = (
                f"MATCH (caller:Function)-[:CALLS*1..{depth}]->(f:Function {{name: $name}}) "
                "RETURN caller.name AS caller, caller.file AS file, caller.start_line AS line "
                "ORDER BY caller.name"
            )
        else:
            query = (
                f"MATCH (f:Function {{name: $name}})-[:CALLS*1..{depth}]->(callee:Function) "
                "RETURN callee.name AS callee, callee.file AS file, callee.start_line AS line "
                "ORDER BY callee.name"
            )

        params = {"name": function_name}
        rows = await self._store.execute_query(query, params)

        key = "caller" if direction == "upstream" else "callee"
        data = [{"name": r[0], "file": r[1], "line": r[2]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_inheritance_tree(self, class_name: str, direction: str = "children") -> QueryResult:
        """Find inheritance hierarchy for a class.

        direction: "children" = subclasses of this class
                   "parents"  = superclasses of this class
        """
        if direction == "parents":
            query = (
                "MATCH (c:Class {name: $name})-[:INHERITS*1..10]->(parent:Class) "
                "RETURN parent.name AS name, parent.file AS file, parent.start_line AS line"
            )
        else:
            query = (
                "MATCH (child:Class)-[:INHERITS*1..10]->(c:Class {name: $name}) "
                "RETURN child.name AS name, child.file AS file, child.start_line AS line"
            )

        params = {"name": class_name}
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "file": r[1], "line": r[2]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_class_methods(self, class_name: str) -> QueryResult:
        """Find all methods belonging to a class."""
        query = (
            "MATCH (c:Class {name: $name})-[:CONTAINS]->(m:Function) "
            "RETURN m.name AS name, m.signature AS signature, m.file AS file, m.start_line AS line "
            "ORDER BY m.start_line"
        )
        params = {"name": class_name}
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "signature": r[1], "file": r[2], "line": r[3]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_module_dependencies(self, module_name: str) -> QueryResult:
        """Find what a module imports."""
        query = (
            "MATCH (m:Module {name: $name})-[:IMPORTS]->(dep:Module) "
            "RETURN dep.name AS name, dep.path AS path"
        )
        params = {"name": module_name}
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_reverse_dependencies(self, module_name: str) -> QueryResult:
        """Find what modules import this module."""
        query = (
            "MATCH (m:Module)-[:IMPORTS]->(dep:Module {name: $name}) "
            "RETURN m.name AS name, m.path AS path"
        )
        params = {"name": module_name}
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_entity(self, name: str, entity_type: str = "any") -> QueryResult:
        """Find a code entity by name (function, class, or module)."""
        if entity_type == "function":
            query = (
                "MATCH (n:Function {name: $name}) "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "n.signature AS signature, n.docstring AS docstring, 'Function' AS type"
            )
        elif entity_type == "class":
            query = (
                "MATCH (n:Class {name: $name}) "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "'' AS signature, n.docstring AS docstring, 'Class' AS type"
            )
        else:
            query = (
                "MATCH (n {name: $name}) "
                "WHERE n:Function OR n:Class OR n:Module "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "coalesce(n.signature, '') AS signature, "
                "coalesce(n.docstring, '') AS docstring, labels(n)[0] AS type"
            )

        params = {"name": name}
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
