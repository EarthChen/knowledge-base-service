"""FalkorDB graph store wrapper for the code knowledge base.

Provides async-compatible connection management, schema initialization
(including vector indexes), and CRUD helpers for graph nodes and edges.
"""

from __future__ import annotations

import asyncio
from typing import Any

from falkordb import FalkorDB, Graph

from config import FalkorDBConfig
from log import get_logger

from .schema import VECTOR_INDEX_CONFIGS, EdgeType, GraphEdge, GraphNode, NodeLabel

log = get_logger(__name__)


class FalkorDBStore:
    """Thin wrapper over FalkorDB for code knowledge graph operations."""

    def __init__(self, config: FalkorDBConfig, embedding_dim: int = 768) -> None:
        self._config = config
        self._embedding_dim = embedding_dim
        self._db: FalkorDB | None = None
        self._graph: Graph | None = None

    async def connect(self) -> None:
        loop = asyncio.get_running_loop()
        self._db = await loop.run_in_executor(None, self._create_connection)
        self._graph = self._db.select_graph(self._config.graph_name)
        log.info(
            "falkordb_connected",
            host=self._config.host,
            port=self._config.port,
            graph=self._config.graph_name,
        )
        await self._ensure_schema()

    def _create_connection(self) -> FalkorDB:
        kwargs: dict[str, Any] = {
            "host": self._config.host,
            "port": self._config.port,
        }
        if self._config.password:
            kwargs["password"] = self._config.password
        return FalkorDB(**kwargs)

    async def _ensure_schema(self) -> None:
        """Create indexes and constraints if they don't exist."""
        loop = asyncio.get_running_loop()

        for label in NodeLabel:
            await loop.run_in_executor(
                None,
                lambda lbl=label: self._graph.query(  # type: ignore[union-attr]
                    f"CREATE INDEX IF NOT EXISTS FOR (n:{lbl}) ON (n.uid)"
                ),
            )

        for idx_cfg in VECTOR_INDEX_CONFIGS:
            try:
                await loop.run_in_executor(
                    None,
                    lambda cfg=idx_cfg: self._graph.query(  # type: ignore[union-attr]
                        f"CREATE VECTOR INDEX IF NOT EXISTS FOR (n:{cfg['label']}) "
                        f"ON (n.{cfg['attribute']}) "
                        f"OPTIONS {{dimension:{self._embedding_dim}, "
                        f"similarityFunction:'{cfg['similarity']}'}}"
                    ),
                )
            except Exception as exc:
                log.warning("vector_index_creation_skipped", label=idx_cfg["label"], error=str(exc))

        log.info("falkordb_schema_ensured")

    async def upsert_node(self, node: GraphNode) -> None:
        loop = asyncio.get_running_loop()
        props = {k: v for k, v in node.properties.items() if k != "embedding"}
        props["uid"] = node.uid

        set_clauses = ", ".join(f"n.{k} = ${k}" for k in props)
        query = (
            f"MERGE (n:{node.label} {{uid: $uid}}) "
            f"ON CREATE SET {set_clauses} "
            f"ON MATCH SET {set_clauses}"
        )

        await loop.run_in_executor(
            None, lambda: self._graph.query(query, params=props)  # type: ignore[union-attr]
        )

    async def set_node_embedding(self, uid: str, label: NodeLabel, embedding: list[float]) -> None:
        loop = asyncio.get_running_loop()
        vec_str = ", ".join(str(v) for v in embedding)
        query = (
            f"MATCH (n:{label} {{uid: $uid}}) "
            f"SET n.embedding = vecf32([{vec_str}])"
        )
        await loop.run_in_executor(
            None, lambda: self._graph.query(query, params={"uid": uid})  # type: ignore[union-attr]
        )

    async def upsert_edge(self, edge: GraphEdge) -> None:
        loop = asyncio.get_running_loop()
        prop_clause = ""
        if edge.properties:
            props_str = ", ".join(f"{k}: ${k}" for k in edge.properties)
            prop_clause = f" {{{props_str}}}"

        query = (
            f"MATCH (a {{uid: $src_uid}}), (b {{uid: $tgt_uid}}) "
            f"MERGE (a)-[r:{edge.edge_type}{prop_clause}]->(b)"
        )
        params: dict[str, Any] = {"src_uid": edge.source_uid, "tgt_uid": edge.target_uid}
        params.update(edge.properties)

        await loop.run_in_executor(
            None, lambda: self._graph.query(query, params=params)  # type: ignore[union-attr]
        )

    async def batch_upsert(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        for node in nodes:
            await self.upsert_node(node)
        for edge in edges:
            await self.upsert_edge(edge)

    async def delete_by_file(self, file_path: str) -> int:
        """Remove all nodes and their edges for a given file path. Returns count deleted."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (n {file: $file}) DETACH DELETE n RETURN count(n) AS deleted",
                params={"file": file_path},
            ),
        )
        deleted = result.result_set[0][0] if result.result_set else 0
        log.info("falkordb_deleted_by_file", file=file_path, deleted=deleted)
        return deleted

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._graph.query(cypher, params=params or {})  # type: ignore[union-attr]
        )
        return result.result_set

    async def vector_search(
        self,
        label: NodeLabel,
        embedding: list[float],
        k: int = 10,
        attribute: str = "embedding",
    ) -> list[tuple[Any, float]]:
        loop = asyncio.get_running_loop()
        vec_str = ", ".join(str(v) for v in embedding)
        query = (
            f"CALL db.idx.vector.queryNodes('{label}', '{attribute}', {k}, "
            f"vecf32([{vec_str}])) YIELD node, score "
            f"RETURN node, score ORDER BY score DESC"
        )
        result = await loop.run_in_executor(
            None, lambda: self._graph.query(query)  # type: ignore[union-attr]
        )
        return [(row[0], row[1]) for row in result.result_set]

    async def close(self) -> None:
        log.info("falkordb_closing")
        if self._db is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._db.connection.close)
            except Exception as exc:
                log.warning("falkordb_close_error", error=str(exc))
        self._graph = None
        self._db = None

    @property
    def graph(self) -> Graph | None:
        return self._graph
