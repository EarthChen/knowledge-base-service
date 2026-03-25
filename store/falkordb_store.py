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


class QueryResultWrapper:
    """Lightweight wrapper around FalkorDB query results.

    Provides both dict-based access via ``.data`` and raw positional access via subscript
    to maintain backward compatibility with callers that use ``result[row][col]``.
    """

    __slots__ = ("data", "raw")

    def __init__(self, data: list[dict[str, Any]], raw: list[list[Any]] | None = None):
        self.data = data
        self.raw = raw or []

    def __getitem__(self, idx: int) -> list[Any]:
        return self.raw[idx]

    def __len__(self) -> int:
        return len(self.raw)

    def __bool__(self) -> bool:
        return bool(self.raw)


class FalkorDBStore:
    """Thin wrapper over FalkorDB for code knowledge graph operations."""

    def __init__(self, config: FalkorDBConfig, embedding_dim: int = 1024) -> None:
        self._config = config
        self._embedding_dim = embedding_dim
        self._db: FalkorDB | None = None
        self._graph: Graph | None = None
        self._owns_connection = True

    @classmethod
    async def from_connection(
        cls,
        db: FalkorDB,
        graph_name: str,
        embedding_dim: int = 1024,
    ) -> "FalkorDBStore":
        """Create a store from an existing FalkorDB connection with a specific graph."""
        instance = cls.__new__(cls)
        instance._config = None  # type: ignore[assignment]
        instance._embedding_dim = embedding_dim
        instance._db = db
        instance._graph = db.select_graph(graph_name)
        instance._owns_connection = False
        await instance._ensure_schema()
        log.info("falkordb_store_from_connection", graph=graph_name)
        return instance

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
            for prop in ("uid", "name", "fqn"):
                try:
                    await loop.run_in_executor(
                        None,
                        lambda lbl=label, p=prop: self._graph.query(  # type: ignore[union-attr]
                            f"CREATE INDEX FOR (n:{lbl}) ON (n.{p})"
                        ),
                    )
                except Exception:
                    pass

        for idx_cfg in VECTOR_INDEX_CONFIGS:
            try:
                await loop.run_in_executor(
                    None,
                    lambda cfg=idx_cfg: self._graph.query(  # type: ignore[union-attr]
                        f"CREATE VECTOR INDEX FOR (n:{cfg['label']}) "
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

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> "QueryResultWrapper":
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._graph.query(cypher, params=params or {})  # type: ignore[union-attr]
        )
        header = [col[1] if isinstance(col, (list, tuple)) else str(col) for col in (result.header or [])]
        data = [dict(zip(header, row)) for row in (result.result_set or [])]
        return QueryResultWrapper(data=data, raw=result.result_set)

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

    async def keyword_search(
        self,
        keyword: str,
        k: int = 10,
        *,
        exact_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Find nodes by name, FQN, or fuzzy CONTAINS match.

        Supports:
        - Simple name: ``checkGeetest``
        - FQN with ``#``: ``com.immomo...EsClient#insert``
        - FQN class only: ``com.immomo...EsClient``

        Returns results sorted by relevance (exact > fqn > fuzzy).
        """
        loop = asyncio.get_running_loop()
        results: list[dict[str, Any]] = []
        seen_uids: set[str] = set()

        _RETURN_CLAUSE = (
            "RETURN n.uid AS uid, n.name AS name, n.file AS file, "
            "n.start_line AS line, labels(n)[0] AS type, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring, "
            "coalesce(n.fqn, '') AS fqn"
        )

        if "#" in keyword or (keyword.count(".") >= 2 and " " not in keyword):
            fqn_q = (
                "MATCH (n) "
                "WHERE (n:Function OR n:Class OR n:Module) AND n.fqn = $fqn "
                f"{_RETURN_CLAUSE} LIMIT $k"
            )
            try:
                rows = await loop.run_in_executor(
                    None,
                    lambda: self._graph.query(fqn_q, params={"fqn": keyword, "k": k}),  # type: ignore[union-attr]
                )
                for row in rows.result_set or []:
                    uid = row[0]
                    if uid and uid not in seen_uids:
                        seen_uids.add(uid)
                        results.append({
                            "uid": uid, "name": row[1], "file": row[2],
                            "line": row[3], "type": row[4], "signature": row[5],
                            "docstring": row[6], "fqn": row[7], "score": 1.0,
                        })
            except Exception as exc:
                log.warning("keyword_fqn_search_error", error=str(exc))

            if results:
                return results[:k]

            if "#" in keyword:
                parts = keyword.rsplit("#", 1)
                method_name = parts[1].split("(")[0].strip() if len(parts) > 1 else ""
                class_fqn = parts[0]
                class_simple = class_fqn.rsplit(".", 1)[-1] if "." in class_fqn else class_fqn
                if method_name:
                    combo_q = (
                        "MATCH (c:Class)-[:CONTAINS]->(f:Function {name: $method}) "
                        "WHERE c.name = $class_name "
                        f"WITH f AS n {_RETURN_CLAUSE} LIMIT $k"
                    )
                    try:
                        rows = await loop.run_in_executor(
                            None,
                            lambda: self._graph.query(  # type: ignore[union-attr]
                                combo_q, params={"method": method_name, "class_name": class_simple, "k": k},
                            ),
                        )
                        for row in rows.result_set or []:
                            uid = row[0]
                            if uid and uid not in seen_uids:
                                seen_uids.add(uid)
                                results.append({
                                    "uid": uid, "name": row[1], "file": row[2],
                                    "line": row[3], "type": row[4], "signature": row[5],
                                    "docstring": row[6], "fqn": row[7], "score": 0.95,
                                })
                    except Exception as exc:
                        log.warning("keyword_combo_search_error", error=str(exc))

            if results:
                return results[:k]

        exact_q = (
            "MATCH (n) "
            "WHERE (n:Function OR n:Class OR n:Module) AND n.name = $name "
            f"{_RETURN_CLAUSE} LIMIT $k"
        )
        try:
            rows = await loop.run_in_executor(
                None,
                lambda: self._graph.query(exact_q, params={"name": keyword, "k": k}),  # type: ignore[union-attr]
            )
            for row in rows.result_set or []:
                uid = row[0]
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    results.append({
                        "uid": uid, "name": row[1], "file": row[2],
                        "line": row[3], "type": row[4], "signature": row[5],
                        "docstring": row[6], "fqn": row[7], "score": 1.0,
                    })
        except Exception as exc:
            log.warning("keyword_exact_search_error", error=str(exc))

        if exact_only or len(results) >= k:
            return results[:k]

        fuzzy_q = (
            "MATCH (n) "
            "WHERE (n:Function OR n:Class OR n:Module) "
            "AND toLower(n.name) CONTAINS toLower($keyword) "
            "AND n.name <> $keyword "
            f"{_RETURN_CLAUSE} "
            "ORDER BY size(n.name) "
            "LIMIT $k"
        )
        try:
            rows = await loop.run_in_executor(
                None,
                lambda: self._graph.query(  # type: ignore[union-attr]
                    fuzzy_q, params={"keyword": keyword, "k": k},
                ),
            )
            for row in rows.result_set or []:
                uid = row[0]
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    results.append({
                        "uid": uid, "name": row[1], "file": row[2],
                        "line": row[3], "type": row[4], "signature": row[5],
                        "docstring": row[6], "fqn": row[7], "score": 0.9,
                    })
        except Exception as exc:
            log.warning("keyword_fuzzy_search_error", error=str(exc))

        return results[:k]

    async def resolve_cross_file_edges(self) -> dict[str, int]:
        """Rebuild INHERITS, IMPORTS, and REFERENCES edges via name-based matching.

        Deletes stale auto-resolved edges first, then recreates from current data.
        This ensures renamed/deleted entities don't leave orphan edges.
        """
        loop = asyncio.get_running_loop()
        stats: dict[str, int] = {}

        for edge_type in ("INHERITS", "IMPORTS", "REFERENCES"):
            try:
                await loop.run_in_executor(
                    None,
                    lambda et=edge_type: self._graph.query(  # type: ignore[union-attr]
                        f"MATCH ()-[r:{et}]->() DELETE r"
                    ),
                )
            except Exception as exc:
                log.warning("stale_edge_cleanup_error", edge_type=edge_type, error=str(exc))

        inherits_q = (
            "MATCH (child:Class) "
            "WHERE child.base_classes IS NOT NULL AND size(child.base_classes) > 0 "
            "UNWIND child.base_classes AS base_name "
            "MATCH (parent:Class {name: base_name}) "
            "WHERE parent.uid <> child.uid "
            "MERGE (child)-[:INHERITS]->(parent) "
            "RETURN count(*) AS cnt"
        )
        try:
            result = await loop.run_in_executor(
                None, lambda: self._graph.query(inherits_q)  # type: ignore[union-attr]
            )
            stats["inherits"] = result.result_set[0][0] if result.result_set else 0
        except Exception as exc:
            log.warning("resolve_inherits_error", error=str(exc))
            stats["inherits"] = 0

        imports_q = (
            "MATCH (m:Module) "
            "WHERE m.imports IS NOT NULL AND size(m.imports) > 0 "
            "UNWIND m.imports AS imp "
            "WITH m, imp, split(imp, '.') AS parts "
            "WITH m, parts[size(parts)-1] AS mod_name "
            "MATCH (target:Module {name: mod_name}) "
            "WHERE target.uid <> m.uid "
            "MERGE (m)-[:IMPORTS]->(target) "
            "RETURN count(*) AS cnt"
        )
        try:
            result = await loop.run_in_executor(
                None, lambda: self._graph.query(imports_q)  # type: ignore[union-attr]
            )
            stats["imports"] = result.result_set[0][0] if result.result_set else 0
        except Exception as exc:
            log.warning("resolve_imports_error", error=str(exc))
            stats["imports"] = 0

        refs_q = (
            "MATCH (d:Document) "
            "WHERE d.code_references IS NOT NULL AND size(d.code_references) > 0 "
            "UNWIND d.code_references AS ref "
            "OPTIONAL MATCH (f:Function {name: ref}) "
            "OPTIONAL MATCH (c:Class {name: ref}) "
            "WITH d, ref, collect(DISTINCT f) + collect(DISTINCT c) AS targets "
            "UNWIND targets AS t "
            "WITH d, t WHERE t IS NOT NULL "
            "MERGE (d)-[:REFERENCES]->(t) "
            "RETURN count(*) AS cnt"
        )
        try:
            result = await loop.run_in_executor(
                None, lambda: self._graph.query(refs_q)  # type: ignore[union-attr]
            )
            stats["references"] = result.result_set[0][0] if result.result_set else 0
        except Exception as exc:
            log.warning("resolve_references_error", error=str(exc))
            stats["references"] = 0

        log.info("cross_file_edges_resolved", **stats)
        return stats

    async def close(self) -> None:
        log.info("falkordb_closing")
        if self._db is not None and self._owns_connection:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._db.connection.close)
            except Exception as exc:
                log.warning("falkordb_close_error", error=str(exc))
        self._graph = None
        if self._owns_connection:
            self._db = None

    @property
    def graph(self) -> Graph | None:
        return self._graph
