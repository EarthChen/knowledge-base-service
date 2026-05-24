"""FalkorDB graph store wrapper for the code knowledge base.

Provides async-compatible connection management, schema initialization
(including vector indexes), and CRUD helpers for graph nodes and edges.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from falkordb import FalkorDB, Graph

from core.config import FalkorDBConfig
from core.log import get_logger
from services.redis_startup import await_with_busy_loading_retry, run_sync_with_busy_loading_retry, run_with_connection_retry
from store.falkordb_common import (  # noqa: F401
    _PARSING_EDGE_TYPES,
    REFERENCES_CROSS_FILE_CYPHER,
    QueryResultWrapper,
    _cypher_escape,
    _graph_executor,
    _wiki_structure_path_case_cypher,
)
from store.falkordb_reads import FalkorDBReadsMixin
from store.falkordb_search import FalkorDBSearchMixin
from store.falkordb_wiki import FalkorDBWikiMixin

from .schema import VECTOR_INDEX_CONFIGS, EdgeType, GraphEdge, GraphNode, NodeLabel, utc_indexed_at_iso

log = get_logger(__name__)

_BATCH_UPSERT_CHUNK = 500


class FalkorDBStore(FalkorDBSearchMixin, FalkorDBWikiMixin, FalkorDBReadsMixin):
    """Thin wrapper over FalkorDB for code knowledge graph operations."""

    _ALLOWED_EDGE_TYPES = frozenset({"CONTAINS", "HAS_CHILD"})
    _ALLOWED_RELATED_EDGE_TYPES = frozenset({
        "CALLS",
        "IMPORTS",
        "INHERITS",
        "IMPLEMENTS",
        "CONTAINS",
        "RELATED_TO",
    })

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
    ) -> FalkorDBStore:
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
        self._db = await run_sync_with_busy_loading_retry(loop, self._create_connection)
        self._graph = self._db.select_graph(self._config.graph_name)
        log.info(
            "falkordb_connected",
            host=self._config.host,
            port=self._config.port,
            graph=self._config.graph_name,
        )
        await await_with_busy_loading_retry(self._ensure_schema)

    def _create_connection(self) -> FalkorDB:
        kwargs: dict[str, Any] = {
            "host": self._config.host,
            "port": self._config.port,
        }
        if self._config.password:
            kwargs["password"] = self._config.password
        return FalkorDB(**kwargs)

    def get_redis_client(self) -> Any | None:
        """Return the underlying Redis client if available.

        Encapsulates internal attribute probing so callers (e.g. wiki bootstrap)
        don't depend on FalkorDB client internals.
        """
        for attr in ("redis", "_redis"):
            conn = getattr(self, attr, None)
            if conn is not None:
                return conn
        graph = getattr(self, "_graph", None)
        if graph is not None:
            for attr in ("_redis", "redis"):
                conn = getattr(graph, attr, None)
                if conn is not None:
                    return conn
        return None

    async def _ensure_schema(self) -> None:
        """Create indexes and constraints if they don't exist."""
        loop = asyncio.get_running_loop()

        for label in NodeLabel:
            for prop in ("uid", "name", "fqn"):
                try:
                    await loop.run_in_executor(
                        _graph_executor,
                        lambda lbl=label, p=prop: self._graph.query(  # type: ignore[union-attr]
                            f"CREATE INDEX FOR (n:{lbl}) ON (n.{p})"
                        ),
                    )
                except Exception as exc:
                    log.warning(
                        "index_create_skipped",
                        label=str(label),
                        prop=prop,
                        reason=str(exc)[:100],
                    )

        for idx_cfg in VECTOR_INDEX_CONFIGS:
            try:
                await loop.run_in_executor(
                    _graph_executor,
                    lambda cfg=idx_cfg: self._graph.query(  # type: ignore[union-attr]
                        f"CREATE VECTOR INDEX FOR (n:{cfg['label']}) "
                        f"ON (n.{cfg['attribute']}) "
                        f"OPTIONS {{dimension:{self._embedding_dim}, "
                        f"similarityFunction:'{cfg['similarity']}'}}"
                    ),
                )
            except Exception as exc:
                log.warning(
                    "vector_index_create_skipped",
                    label=idx_cfg["label"],
                    reason=str(exc)[:100],
                )

        log.info("falkordb_schema_ensured")

    _VALID_PROP_KEY_RE = __import__("re").compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    async def upsert_node(self, node: GraphNode) -> None:
        loop = asyncio.get_running_loop()
        props = {
            k: v
            for k, v in node.properties.items()
            if k != "embedding" and self._VALID_PROP_KEY_RE.match(k)
        }
        props["uid"] = node.uid

        set_clauses = ", ".join(f"n.{k} = ${k}" for k in props)
        query = (
            f"MERGE (n:{node.label} {{uid: $uid}}) "
            f"ON CREATE SET {set_clauses} "
            f"ON MATCH SET {set_clauses}"
        )

        await loop.run_in_executor(
            _graph_executor, lambda: self._graph.query(query, params=props)  # type: ignore[union-attr]
        )

    async def set_node_embedding(self, uid: str, label: NodeLabel, embedding: list[float]) -> None:
        loop = asyncio.get_running_loop()
        vec_str = ", ".join(str(v) for v in embedding)
        query = (
            f"MATCH (n:{label} {{uid: $uid}}) "
            f"SET n.embedding = vecf32([{vec_str}])"
        )
        await loop.run_in_executor(
            _graph_executor, lambda: self._graph.query(query, params={"uid": uid})  # type: ignore[union-attr]
        )

    async def batch_set_node_embeddings(
        self,
        items: list[tuple[str, NodeLabel, list[float]]],
        *,
        concurrency: int = 5,
    ) -> None:
        """Set embeddings for many nodes with bounded parallel ``set_node_embedding`` calls.

        FalkorDB/RedisGraph cannot efficiently pass vector params through UNWIND; use
        limited concurrency instead of a single Cypher UNWIND.
        """
        if not items:
            return
        sem = asyncio.Semaphore(concurrency)

        async def _one(uid: str, label: NodeLabel, emb: list[float]) -> None:
            async with sem:
                await self.set_node_embedding(uid, label, emb)

        await asyncio.gather(*[_one(u, lb, e) for u, lb, e in items])

    _ALLOWED_PROPERTIES = frozenset({
        "business_summary", "business_domain", "description", "embedding", "fqn",
        "content_hash", "confidence_score", "category", "source", "aliases",
        "memory_status", "stability_factor", "last_accessed",
    })

    async def update_node_property(
        self, label: NodeLabel, uid: str, prop: str, value: object
    ) -> None:
        """Update a single property on an existing node.

        Only properties in _ALLOWED_PROPERTIES can be set to prevent Cypher injection.
        """
        if prop not in self._ALLOWED_PROPERTIES:
            raise ValueError(f"Property '{prop}' is not in the allowed whitelist")
        loop = asyncio.get_running_loop()
        query = f"MATCH (n:{label} {{uid: $uid}}) SET n.{prop} = $value"
        await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                query, params={"uid": uid, "value": value}
            ),
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
            _graph_executor, lambda: self._graph.query(query, params=params)  # type: ignore[union-attr]
        )

    async def _batch_upsert_nodes_for_label(
        self, label: NodeLabel, nodes: list[GraphNode],
    ) -> None:
        if not nodes:
            return
        loop = asyncio.get_running_loop()
        items: list[dict[str, Any]] = []
        for node in nodes:
            props = {k: v for k, v in node.properties.items() if k != "embedding"}
            props["uid"] = node.uid
            items.append({"uid": node.uid, "props": props})
        query = (
            f"UNWIND $items AS item "
            f"MERGE (n:{label} {{uid: item.uid}}) "
            f"SET n += item.props"
        )
        for i in range(0, len(items), _BATCH_UPSERT_CHUNK):
            batch = items[i : i + _BATCH_UPSERT_CHUNK]
            await loop.run_in_executor(
                _graph_executor,
                lambda b=batch, q=query: self._graph.query(q, params={"items": b}),  # type: ignore[union-attr]
            )

    async def _batch_upsert_edges_for_type(
        self, edge_type: EdgeType, edges: list[GraphEdge],
    ) -> None:
        if not edges:
            return
        loop = asyncio.get_running_loop()
        items = [
            {
                "source_uid": edge.source_uid,
                "target_uid": edge.target_uid,
                "props": dict(edge.properties),
            }
            for edge in edges
        ]
        query = (
            "UNWIND $items AS item "
            "MATCH (a {uid: item.source_uid}), (b {uid: item.target_uid}) "
            f"MERGE (a)-[r:{edge_type.value}]->(b) "
            "SET r += item.props "
            "RETURN count(*) AS upserted"
        )
        total_input = 0
        total_upserted = 0
        for i in range(0, len(items), _BATCH_UPSERT_CHUNK):
            batch = items[i : i + _BATCH_UPSERT_CHUNK]
            total_input += len(batch)

            def _run_batch(b: list[dict[str, Any]] = batch, q: str = query) -> Any:
                return self._graph.query(q, params={"items": b})  # type: ignore[union-attr]

            result = await loop.run_in_executor(_graph_executor, _run_batch)
            upserted = int(result.result_set[0][0]) if result.result_set else 0
            total_upserted += upserted

        skipped = total_input - total_upserted
        if skipped > 0:
            log.warning(
                "batch_edge_upsert_skipped",
                edge_type=edge_type.value,
                input_count=total_input,
                upserted_count=total_upserted,
                skipped_count=skipped,
            )

    async def batch_upsert(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        if nodes:
            by_label: dict[NodeLabel, list[GraphNode]] = defaultdict(list)
            for node in nodes:
                by_label[node.label].append(node)
            for label, group in by_label.items():
                await self._batch_upsert_nodes_for_label(label, group)
        if edges:
            by_type: dict[EdgeType, list[GraphEdge]] = defaultdict(list)
            for edge in edges:
                by_type[edge.edge_type].append(edge)
            for edge_type, group in by_type.items():
                await self._batch_upsert_edges_for_type(edge_type, group)

    async def get_nodes_by_file(self, file_path: str) -> list:
        """Retrieve embeddable nodes (Function, Class, Document, Chunk) for a given file path."""
        from store.schema import GraphNode

        loop = asyncio.get_running_loop()
        cypher = (
            "MATCH (n) "
            "WHERE (n:Function OR n:Class OR n:Document OR n:Chunk) AND n.file = $file "
            "RETURN n"
        )
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(cypher, params={"file": file_path}),  # type: ignore[union-attr]
        )
        nodes: list = []
        for row in result.result_set or []:
            node_data = row[0] if row else None
            if node_data and hasattr(node_data, "properties"):
                props = dict(node_data.properties)
                label_str = "Function"
                if hasattr(node_data, "labels") and node_data.labels:
                    label_str = node_data.labels[0]
                label = NodeLabel(label_str)
                uid = props.pop("uid", "") or f"{label}:{file_path}:{props.get('name', '')}:{props.get('start_line', 0)}"  # noqa: E501
                nodes.append(GraphNode(label=label, properties=props, uid=uid))
        return nodes

    async def delete_by_file(self, file_path: str) -> int:
        """Remove all nodes and their edges for a given file path. Returns count deleted.

        Code entities use the ``file`` property; :Module nodes for a source file store the
        path as ``path`` (see ``CodeGraphBuilder``). Match both so modules and their edges
        are removed. Import placeholder modules use ``path`` like ``<import:foo>`` and do
        not equal real file paths, so they are unaffected.
        """
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (n) WHERE n.file = $file OR (n:Module AND n.path = $file) "
                "DETACH DELETE n RETURN count(n) AS deleted",
                params={"file": file_path},
            ),
        )
        deleted = result.result_set[0][0] if result.result_set else 0
        log.info("falkordb_deleted_by_file", file=file_path, deleted=deleted)
        return deleted

    async def get_chunk_hashes_for_file(self, file_path: str) -> dict[str, str]:
        """Return ``uid -> content_hash`` for embeddable nodes (Function, Class, Document, Chunk).

        Labels that are not in the result set, or with missing ``content_hash``,
        are returned with empty string so callers treat them as *needs re-embed*.
        """
        return await self.get_chunk_hashes_for_files([file_path])

    async def get_chunk_hashes_for_files(self, file_paths: list[str] | set[str]) -> dict[str, str]:
        """Same as :meth:`get_chunk_hashes_for_file` for one or more ``n.file`` keys (merged)."""
        paths = [p for p in (file_paths if isinstance(file_paths, list) else set(file_paths)) if p]
        if not paths:
            return {}
        loop = asyncio.get_running_loop()
        cypher = (
            "MATCH (n) "
            "WHERE (n:Function OR n:Class OR n:Document OR n:Chunk) AND n.file IN $files "
            "RETURN n.uid AS uid, coalesce(n.content_hash, '') AS content_hash"
        )
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                cypher, params={"files": list(paths)},
            ),
        )
        out: dict[str, str] = {}
        for row in result.result_set or []:
            if not row:
                continue
            uid = str(row[0] or "")
            ch = str(row[1] or "")
            if uid:
                out[uid] = ch
        return out

    async def get_node_uids_for_file(self, file_path: str) -> set[str]:
        """All node UIDs for this *file* key (``file`` or Module ``path``), including Module."""
        return await self.get_node_uids_for_files([file_path])

    async def get_node_uids_for_files(self, file_paths: list[str] | set[str]) -> set[str]:
        """Like :meth:`get_node_uids_for_file` for multiple path keys (union of UIDs)."""
        paths = [p for p in (file_paths if isinstance(file_paths, list) else set(file_paths)) if p]
        if not paths:
            return set()
        loop = asyncio.get_running_loop()
        fl = list(paths)
        cypher = (
            "MATCH (n) "
            "WHERE n.file IN $files OR (n:Module AND n.path IN $files) "
            "RETURN n.uid AS uid"
        )
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                cypher, params={"files": fl},
            ),
        )
        uids: set[str] = set()
        for row in result.result_set or []:
            if row and row[0]:
                uids.add(str(row[0]))
        return uids

    async def get_module_structural_hash(self, file_path: str) -> str | None:
        """Return stored ``structural_hash`` for the Module node at *file_path*, if any."""
        loop = asyncio.get_running_loop()
        cypher = (
            "MATCH (m:Module) WHERE m.path = $path "
            "RETURN m.structural_hash AS sh LIMIT 1"
        )
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                cypher, params={"path": file_path},
            ),
        )
        for row in result.result_set or []:
            if row and row[0]:
                return str(row[0])
        return None

    async def update_module_metadata(self, file_path: str, *, commit_sha: str | None = None) -> None:
        """Update Module indexing metadata without a full structural re-upsert."""
        loop = asyncio.get_running_loop()
        cypher = (
            "MATCH (m:Module) WHERE m.path = $path "
            "SET m.commit_sha = $sha, m.indexed_at = $ts"
        )
        await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                cypher,
                params={
                    "path": file_path,
                    "sha": commit_sha or "",
                    "ts": utc_indexed_at_iso(),
                },
            ),
        )

    async def delete_parser_edges_for_file(self, file_path: str) -> None:
        """Delete indexing-time edges that touch nodes belonging to *file_path* (see :meth:`delete_parser_edges_for_files`)."""  # noqa: E501
        await self.delete_parser_edges_for_files([file_path])

    async def delete_parser_edges_for_files(self, file_paths: list[str] | set[str]) -> None:
        """Delete parsing pipeline edges that touch any of the given *file* / Module *path* keys.

        See :data:`_PARSING_EDGE_TYPES`. Cross-file *CALLS* / *IMPORTS* involving
        these paths are removed and recreated by the next :meth:`batch_upsert`.
        """
        paths = [p for p in (file_paths if isinstance(file_paths, list) else set(file_paths)) if p]
        if not paths:
            return
        loop = asyncio.get_running_loop()
        fl = list(paths)
        cypher = (
            "MATCH (a)-[r]->(b) "
            "WHERE type(r) IN $types AND ("
            "  (a:Module AND a.path IN $files) OR (b:Module AND b.path IN $files) "
            "  OR a.file IN $files OR b.file IN $files) "
            "DELETE r"
        )
        await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                cypher,
                params={"files": fl, "types": list(_PARSING_EDGE_TYPES)},
            ),
        )
        log.info("falkordb_parser_edges_deleted", files=fl, types=_PARSING_EDGE_TYPES)

    async def delete_nodes_by_uids(self, uids: list[str]) -> int:
        """``DETACH DELETE`` nodes with the given UIDs. Returns the number of deletes attempted."""
        if not uids:
            return 0
        loop = asyncio.get_running_loop()
        cypher = "UNWIND $uids AS u MATCH (n {uid: u}) DETACH DELETE n RETURN count(n) AS c"
        total = 0
        step = 500
        for i in range(0, len(uids), step):
            batch = uids[i : i + step]
            result = await loop.run_in_executor(
                _graph_executor,
                lambda b=batch: self._graph.query(  # type: ignore[union-attr]
                    cypher, params={"uids": b}
                ),
            )
            if result.result_set and result.result_set[0]:
                total += int(result.result_set[0][0] or 0)
        return total

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
        result = await run_with_connection_retry(
            _graph_executor,
            lambda: self._graph.query(cypher, params=params or {}),  # type: ignore[union-attr]
        )
        header = [col[1] if isinstance(col, (list, tuple)) else str(col) for col in (result.header or [])]
        data = [dict(zip(header, row)) for row in (result.result_set or [])]
        return QueryResultWrapper(data=data, raw=result.result_set)

    async def find_edges_between(
        self,
        repository: str,
        paths: list[str],
        edge_types: list[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Find CALLS/IMPORTS-style edges whose endpoints resolve to wiki structure paths.

        Each returned tuple is ``(source_path, target_path)`` matching
        :meth:`wiki.structure_planner.WikiStructurePlanner._structure_path` string rules
        so they can be fed to :func:`wiki.delegation.group_children_by_graph`.

        Empty *paths* returns immediately (no scan).
        """
        if not paths:
            return []
        types = edge_types or ["CALLS", "IMPORTS"]
        repo = (repository or "").strip()
        sa_expr = _wiki_structure_path_case_cypher("a")
        sb_expr = _wiki_structure_path_case_cypher("b")
        cypher = (
            "MATCH (a)-[r]->(b) "
            "WHERE a.repository = $repo AND b.repository = $repo "
            "AND type(r) IN $edge_types "
            "AND (a:Function OR a:Class OR a:Module) "
            "AND (b:Function OR b:Class OR b:Module) "
            f"WITH a, b, {sa_expr} AS sa, {sb_expr} AS sb "
            "WHERE sa IN $paths AND sb IN $paths AND sa <> sb "
            "RETURN DISTINCT sa AS source, sb AS target"
        )
        result = await self.execute_query(
            cypher,
            {"repo": repo, "paths": paths, "edge_types": types},
        )
        out: list[tuple[str, str]] = []
        for row in result.data:
            s, t = row.get("source"), row.get("target")
            if s is not None and t is not None and str(s) and str(t):
                out.append((str(s), str(t)))
        return out

    async def close(self) -> None:
        log.info("falkordb_closing")
        if self._db is not None and self._owns_connection:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(_graph_executor, self._db.connection.close)
            except Exception as exc:
                log.warning("falkordb_close_error", error=str(exc))
        self._graph = None
        if self._owns_connection:
            self._db = None

    @property
    def graph(self) -> Graph | None:
        return self._graph
