"""Hybrid query interface — combines graph traversal with semantic search.

Provides compound queries that first find semantically relevant entities,
then expand them via graph relationships to discover related code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from log import get_logger

from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel
from query.graph_query import GraphQueryService
from query.semantic_query import SemanticQueryService

log = get_logger(__name__)


@dataclass
class HybridResult:
    semantic_matches: list[dict[str, Any]] = field(default_factory=list)
    graph_context: list[dict[str, Any]] = field(default_factory=list)
    query_text: str = ""
    total: int = 0


class HybridQueryService:
    """Combines semantic search with graph traversal for richer results."""

    def __init__(
        self,
        store: FalkorDBStore,
        semantic_svc: SemanticQueryService,
        graph_svc: GraphQueryService,
    ) -> None:
        self._store = store
        self._semantic = semantic_svc
        self._graph = graph_svc

    async def search_with_context(
        self,
        query_text: str,
        k: int = 5,
        expand_depth: int = 2,
        include_callers: bool = True,
        include_callees: bool = True,
    ) -> HybridResult:
        """Semantic search + graph expansion for comprehensive context.

        1. Find top-k semantically similar entities
        2. For each Function, expand via CALLS edges
        3. For each Class, expand via CONTAINS edges
        """
        semantic_result = await self._semantic.search_all(query_text, k)

        graph_context: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        for match in semantic_result.matches:
            name = match.get("name", "")
            entity_type = match.get("type", "")

            if name in seen_names or not name:
                continue
            seen_names.add(name)

            if entity_type == str(NodeLabel.FUNCTION):
                if include_callees:
                    callees = await self._graph.find_call_chain(name, depth=expand_depth, direction="downstream")
                    for item in callees.data:
                        item["relationship"] = "called_by"
                        item["source"] = name
                        graph_context.append(item)

                if include_callers:
                    callers = await self._graph.find_call_chain(name, depth=expand_depth, direction="upstream")
                    for item in callers.data:
                        item["relationship"] = "calls"
                        item["source"] = name
                        graph_context.append(item)

            elif entity_type == str(NodeLabel.CLASS):
                methods = await self._graph.find_class_methods(name)
                for item in methods.data:
                    item["relationship"] = "method_of"
                    item["source"] = name
                    graph_context.append(item)

                children = await self._graph.find_inheritance_tree(name, direction="children")
                for item in children.data:
                    item["relationship"] = "subclass_of"
                    item["source"] = name
                    graph_context.append(item)

        unique_context = self._deduplicate(graph_context)

        return HybridResult(
            semantic_matches=semantic_result.matches,
            graph_context=unique_context,
            query_text=query_text,
            total=len(semantic_result.matches) + len(unique_context),
        )

    async def find_related_to_file(self, file_path: str) -> HybridResult:
        """Find all entities in a file and their graph relationships."""
        entities = await self._graph.find_file_entities(file_path)

        graph_context: list[dict[str, Any]] = []
        for entity in entities.data:
            name = entity.get("name", "")
            entity_type = entity.get("type", "")

            if entity_type == "Function":
                callees = await self._graph.find_call_chain(name, depth=1, direction="downstream")
                for item in callees.data:
                    item["relationship"] = "called_by"
                    item["source"] = name
                    graph_context.append(item)

            elif entity_type == "Class":
                methods = await self._graph.find_class_methods(name)
                for item in methods.data:
                    item["relationship"] = "method_of"
                    item["source"] = name
                    graph_context.append(item)

        return HybridResult(
            semantic_matches=[{"type": e.get("type", ""), "name": e.get("name", "")} for e in entities.data],
            graph_context=self._deduplicate(graph_context),
            query_text=f"file:{file_path}",
            total=len(entities.data) + len(graph_context),
        )

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            key = f"{item.get('name', '')}:{item.get('file', '')}:{item.get('line', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique
