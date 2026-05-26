"""Entity explanation service for MCP wiki_explain tool."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class EntityExplainer:
    def __init__(self, graph: _GraphPort) -> None:
        self._graph = graph

    async def explain(self, repository: str, entity_name: str) -> dict[str, Any]:
        """Fetch entity details: signature, docstring, relationships, and wiki page content."""
        entity_q = (
            "MATCH (e {repository: $repo}) "
            "WHERE e.name = $name OR e.fqn = $name "
            "RETURN e.name AS name, e.fqn AS fqn, e.type AS type, "
            "       e.signature AS signature, e.docstring AS docstring, "
            "       e.file AS file, e.start_line AS start_line "
            "LIMIT 1"
        )
        result = await self._graph.execute_query(entity_q, {"repo": repository, "name": entity_name})
        rows = getattr(result, "data", []) or []

        if not rows:
            return {"found": False, "entity": entity_name, "repository": repository}

        row = rows[0] if isinstance(rows[0], dict) else {}

        # Fetch relationships
        rel_q = (
            "MATCH (e {repository: $repo})-[r]-(other) "
            "WHERE e.name = $name OR e.fqn = $name "
            "RETURN type(r) AS rel_type, other.name AS other_name, "
            "       other.type AS other_type "
            "LIMIT 20"
        )
        rel_result = await self._graph.execute_query(rel_q, {"repo": repository, "name": entity_name})
        rel_rows = getattr(rel_result, "data", []) or []
        relationships = [r for r in rel_rows if isinstance(r, dict)]

        # Fetch wiki page content
        wiki_q = (
            "MATCH (wp:WikiPage)-[:SOURCE_ENTITY]->(e {repository: $repo}) "
            "WHERE e.name = $name OR e.fqn = $name "
            "RETURN wp.title AS title, wp.content AS content, wp.path AS page_path "
            "LIMIT 1"
        )
        wiki_result = await self._graph.execute_query(wiki_q, {"repo": repository, "name": entity_name})
        wiki_rows = getattr(wiki_result, "data", []) or []
        wiki_page = wiki_rows[0] if wiki_rows and isinstance(wiki_rows[0], dict) else {}

        return {
            "found": True,
            "entity": {
                "name": row.get("name", ""),
                "fqn": row.get("fqn", ""),
                "type": row.get("type", ""),
                "signature": row.get("signature", ""),
                "docstring": row.get("docstring", ""),
                "file": row.get("file", ""),
                "start_line": row.get("start_line", 0),
            },
            "relationships": relationships,
            "wiki_page": wiki_page,
        }
