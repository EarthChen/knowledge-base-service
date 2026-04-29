"""FalkorDB graph store wrapper for the code knowledge base.

Provides async-compatible connection management, schema initialization
(including vector indexes), and CRUD helpers for graph nodes and edges.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from falkordb import FalkorDB, Graph

from config import FalkorDBConfig
from log import get_logger
from services.redis_startup import await_with_busy_loading_retry, run_sync_with_busy_loading_retry

from .schema import VECTOR_INDEX_CONFIGS, EdgeType, GraphEdge, GraphNode, NodeLabel

# Edges (re)created by the code/doc indexer for a file — cleared before re-upsert
# in incremental mode so MERGE does not leave stale relations.
_PARSING_EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "CONTAINS",
    "INHERITS",
    "IMPLEMENTS",
    "IMPORTS",
    "PART_OF",
    "PROVIDES_RPC",
    "CONSUMES_RPC",
)

log = get_logger(__name__)

_graph_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="falkordb")
_xref_lock = asyncio.Lock()


def _cypher_escape(value: str) -> str:
    """Escape single quotes in a string for safe Cypher literal interpolation."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _wiki_structure_path_case_cypher(var: str) -> str:
    """OpenCypher CASE for wiki layout path aligned with WikiStructurePlanner._structure_path."""

    return (
        f"CASE "
        f"WHEN {var}:Module THEN coalesce({var}.path, toString({var}.name), {var}.uid) "
        f"WHEN {var}:Class THEN coalesce({var}.fqn, toString({var}.name), {var}.uid) "
        f"WHEN {var}.file IS NOT NULL AND {var}.name IS NOT NULL "
        f"AND toString({var}.file) <> '' AND toString({var}.name) <> '' "
        f"THEN toString({var}.file) + '#' + toString({var}.name) "
        f"ELSE coalesce(toString({var}.fqn), toString({var}.name), {var}.uid) END"
    )


# Cross-file REFERENCES rebuild: FQN match, then same-name + doc directory prefix, then name-only.
REFERENCES_CROSS_FILE_CYPHER = """
MATCH (d:Document)
WHERE d.code_references IS NOT NULL AND size(d.code_references) > 0
UNWIND d.code_references AS ref
WITH d, ref, split(d.file, '/') AS segs
WITH d, ref,
  CASE WHEN size(segs) < 2 THEN NULL
       ELSE reduce(s = segs[0], i IN range(1, size(segs)-1) | s + '/' + segs[i]) + '/' END AS doc_dir
OPTIONAL MATCH (f1:Function)
WHERE f1.fqn = ref
OPTIONAL MATCH (c1:Class)
WHERE c1.fqn = ref
WITH d, ref, doc_dir, collect(DISTINCT f1) + collect(DISTINCT c1) AS fqn_hits
OPTIONAL MATCH (f2:Function)
WHERE size(fqn_hits) = 0 AND f2.name = ref AND doc_dir IS NOT NULL AND f2.file STARTS WITH doc_dir
OPTIONAL MATCH (c2:Class)
WHERE size(fqn_hits) = 0 AND c2.name = ref AND doc_dir IS NOT NULL AND c2.file STARTS WITH doc_dir
WITH d, ref, fqn_hits, collect(DISTINCT f2) + collect(DISTINCT c2) AS dir_hits
OPTIONAL MATCH (f3:Function)
WHERE size(fqn_hits) = 0 AND size(dir_hits) = 0 AND f3.name = ref
OPTIONAL MATCH (c3:Class)
WHERE size(fqn_hits) = 0 AND size(dir_hits) = 0 AND c3.name = ref
WITH d, ref,
  CASE WHEN size(fqn_hits) > 0 THEN fqn_hits
       WHEN size(dir_hits) > 0 THEN dir_hits
       ELSE collect(DISTINCT f3) + collect(DISTINCT c3) END AS targets
UNWIND targets AS t
WITH d, t
WHERE t IS NOT NULL
MERGE (d)-[:REFERENCES]->(t)
RETURN count(*) AS cnt
""".strip()


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

    @property
    def result_set(self) -> list[list[Any]]:
        """Alias for ``raw`` (FalkorDB positional rows); older callers use this name."""
        return self.raw


class FalkorDBStore:
    """Thin wrapper over FalkorDB for code knowledge graph operations."""

    _ALLOWED_EDGE_TYPES = frozenset({"CONTAINS", "HAS_CHILD"})

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
                except Exception:
                    pass

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

    async def batch_upsert(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        for node in nodes:
            await self.upsert_node(node)
        for edge in edges:
            await self.upsert_edge(edge)

    async def get_nodes_by_file(self, file_path: str) -> list:
        """Retrieve embeddable nodes (Function, Class, Document, Chunk) for a given file path."""
        from store.schema import GraphNode

        embeddable_labels = ["Function", "Class", "Document", "Chunk"]
        nodes: list = []
        loop = asyncio.get_running_loop()
        for lbl in embeddable_labels:
            cypher = f"MATCH (n:{lbl} {{file: $file}}) RETURN n"
            result = await loop.run_in_executor(
                _graph_executor,
                lambda q=cypher: self._graph.query(q, params={"file": file_path}),  # type: ignore[union-attr]
            )
            for row in result.result_set or []:
                node_data = row[0] if row else None
                if node_data and hasattr(node_data, "properties"):
                    props = dict(node_data.properties)
                    label = NodeLabel(lbl)
                    uid = props.pop("uid", "") or f"{label}:{file_path}:{props.get('name', '')}:{props.get('start_line', 0)}"
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

    async def delete_parser_edges_for_file(self, file_path: str) -> None:
        """Delete indexing-time edges that touch nodes belonging to *file_path* (see :meth:`delete_parser_edges_for_files`)."""
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
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(cypher, params=params or {})  # type: ignore[union-attr]
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

    async def get_repository_index_freshness(self, repository: str) -> dict[str, Any]:
        """Aggregate index freshness for nodes stamped with ``repository``."""
        repo = (repository or "").strip()
        q_stats = (
            "MATCH (n) WHERE n.repository = $repo "
            "RETURN max(n.indexed_at) AS last_indexed_at, count(n) AS node_count"
        )
        stats = await self.execute_query(q_stats, {"repo": repo})
        last_indexed_at: str | None = None
        node_count = 0
        if stats.data:
            row = stats.data[0]
            last_indexed_at = row.get("last_indexed_at")
            if last_indexed_at is not None:
                last_indexed_at = str(last_indexed_at)
            raw_cnt = row.get("node_count")
            try:
                node_count = int(raw_cnt) if raw_cnt is not None else 0
            except (TypeError, ValueError):
                node_count = 0

        commit_sha: str | None = None
        q_sha = (
            "MATCH (n) WHERE n.repository = $repo AND n.commit_sha IS NOT NULL "
            "RETURN n.commit_sha AS commit_sha "
            "ORDER BY n.indexed_at DESC LIMIT 1"
        )
        sha_res = await self.execute_query(q_sha, {"repo": repo})
        if sha_res.data:
            cs = sha_res.data[0].get("commit_sha")
            if cs is not None and str(cs).strip():
                commit_sha = str(cs).strip()

        return {
            "repository": repo,
            "last_indexed_at": last_indexed_at,
            "node_count": node_count,
            "commit_sha": commit_sha,
        }

    async def persist_wiki_pages(self, repository: str, pages: list[dict[str, Any]]) -> int:
        """MERGE WikiPage nodes from generated wiki output. Returns count of upserted nodes."""
        if not pages:
            return 0
        batch: list[dict[str, Any]] = []
        for page in pages:
            path = page["path"]
            batch.append(
                {
                    "uid": f"WikiPage:{repository}:{path}",
                    "repository": repository,
                    "path": path,
                    "title": page["title"],
                    "content": page["content"],
                    "page_type": page["page_type"],
                    "generated_at": page["generated_at"],
                    "version": page.get("version", 1),
                    "content_hash": page.get("content_hash", ""),
                    "importance_tier": page.get("importance_tier", ""),
                    "enrichment_level": ""
                    if page.get("enrichment_level") is None
                    else str(page.get("enrichment_level")),
                    "repositories": page.get("repositories", [repository]),
                    "confidence_score": page.get("confidence_score"),
                    "source_origin": page.get("source_origin", ""),
                    "navigation_json": page.get("navigation_json") or "",
                }
            )
        cypher = (
            "UNWIND $batch AS page "
            "MERGE (w:WikiPage {uid: page.uid}) "
            "SET w.repository = page.repository, "
            "w.path = page.path, "
            "w.title = page.title, "
            "w.content = page.content, "
            "w.page_type = page.page_type, "
            "w.generated_at = page.generated_at, "
            "w.version = page.version, "
            "w.content_hash = page.content_hash, "
            "w.importance_tier = page.importance_tier, "
            "w.enrichment_level = page.enrichment_level, "
            "w.repositories = page.repositories, "
            "w.confidence_score = coalesce(page.confidence_score, w.confidence_score), "
            "w.navigation_json = page.navigation_json, "
            "w.source_origin = CASE "
            "WHEN page.source_origin IS NULL OR page.source_origin = '' "
            "THEN w.source_origin ELSE page.source_origin END "
            "RETURN count(*) AS cnt"
        )
        result = await self.execute_query(cypher, {"batch": batch})
        if not result.data:
            return len(batch)
        cnt = result.data[0].get("cnt")
        if cnt is None:
            return len(batch)
        return int(cnt)

    async def vector_search(
        self,
        label: NodeLabel,
        embedding: list[float],
        k: int = 10,
        attribute: str = "embedding",
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> list[tuple[Any, float]]:
        loop = asyncio.get_running_loop()
        vec_str = ", ".join(str(v) for v in embedding)

        where_parts: list[str] = []
        if repository:
            where_parts.append(f"node.repository = '{_cypher_escape(repository)}'")
        if language:
            where_parts.append(f"node.language = '{_cypher_escape(language)}'")

        fetch_k = k * 3 if where_parts else k
        where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""

        query = (
            f"CALL db.idx.vector.queryNodes('{label}', '{attribute}', {fetch_k}, "
            f"vecf32([{vec_str}])) YIELD node, score"
            f"{where_clause} "
            f"RETURN node, score ORDER BY score DESC LIMIT {k}"
        )
        result = await loop.run_in_executor(
            _graph_executor, lambda: self._graph.query(query)  # type: ignore[union-attr]
        )
        return [(row[0], row[1]) for row in result.result_set]

    async def keyword_search(
        self,
        keyword: str,
        k: int = 10,
        *,
        exact_only: bool = False,
        repository: str | None = None,
        language: str | None = None,
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

        extra_filters: list[str] = []
        if repository:
            extra_filters.append(f"n.repository = '{_cypher_escape(repository)}'")
        if language:
            extra_filters.append(f"n.language = '{_cypher_escape(language)}'")
        _kw_filter = (" AND " + " AND ".join(extra_filters)) if extra_filters else ""

        return_clause = (
            "RETURN n.uid AS uid, n.name AS name, n.file AS file, "
            "n.start_line AS line, labels(n)[0] AS type, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring, "
            "coalesce(n.fqn, '') AS fqn"
        )

        if "#" in keyword or (keyword.count(".") >= 2 and " " not in keyword):
            fqn_q = (
                "MATCH (n) "
                f"WHERE (n:Function OR n:Class OR n:Module) AND n.fqn = $fqn{_kw_filter} "
                f"{return_clause} LIMIT $k"
            )
            try:
                rows = await loop.run_in_executor(
                    _graph_executor,
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
                    combo_class_filter = _kw_filter.replace("n.", "c.")
                    combo_func_filter = _kw_filter.replace("n.", "f.")
                    combo_q = (
                        "MATCH (c:Class)-[:CONTAINS]->(f:Function {name: $method}) "
                        f"WHERE c.name = $class_name{combo_class_filter}{combo_func_filter} "
                        f"WITH f AS n {return_clause} LIMIT $k"
                    )
                    try:
                        rows = await loop.run_in_executor(
                            _graph_executor,
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
            f"WHERE (n:Function OR n:Class OR n:Module) AND n.name = $name{_kw_filter} "
            f"{return_clause} LIMIT $k"
        )
        try:
            rows = await loop.run_in_executor(
                _graph_executor,
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
            f"AND n.name <> $keyword{_kw_filter} "
            f"{return_clause} "
            "ORDER BY size(n.name) "
            "LIMIT $k"
        )
        try:
            rows = await loop.run_in_executor(
                _graph_executor,
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
        async with _xref_lock:
            loop = asyncio.get_running_loop()
            stats: dict[str, int] = {}

            for edge_type in ("INHERITS", "IMPORTS", "REFERENCES"):
                try:
                    await loop.run_in_executor(
                        _graph_executor,
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
                    _graph_executor, lambda: self._graph.query(inherits_q)  # type: ignore[union-attr]
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
                "WHERE NOT (starts_with(imp, 'java.') OR starts_with(imp, 'javax.') "
                "OR starts_with(imp, 'jdk.') OR starts_with(imp, 'sun.') "
                "OR starts_with(imp, 'com.sun.') OR starts_with(imp, 'org.w3c.') "
                "OR starts_with(imp, 'org.xml.') OR starts_with(imp, 'org.ietf.')) "
                "WITH m, parts[size(parts)-1] AS mod_name "
                "MATCH (target:Module {name: mod_name}) "
                "WHERE target.uid <> m.uid "
                "MERGE (m)-[:IMPORTS]->(target) "
                "RETURN count(*) AS cnt"
            )
            try:
                result = await loop.run_in_executor(
                    _graph_executor, lambda: self._graph.query(imports_q)  # type: ignore[union-attr]
                )
                stats["imports"] = result.result_set[0][0] if result.result_set else 0
            except Exception as exc:
                log.warning("resolve_imports_error", error=str(exc))
                stats["imports"] = 0

            try:
                result = await loop.run_in_executor(
                    _graph_executor,
                    lambda: self._graph.query(REFERENCES_CROSS_FILE_CYPHER),  # type: ignore[union-attr]
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
                await loop.run_in_executor(_graph_executor, self._db.connection.close)
            except Exception as exc:
                log.warning("falkordb_close_error", error=str(exc))
        self._graph = None
        if self._owns_connection:
            self._db = None

    # ── GraphQueryPort / DataCollectorPort protocol methods ────

    def _row_to_graph_node(self, row_node: Any) -> GraphNode | None:
        """Convert a FalkorDB result node into a ``GraphNode``."""
        if row_node is None or not hasattr(row_node, "properties"):
            return None
        props = dict(row_node.properties)
        uid = str(props.pop("uid", ""))
        label_str: str = ""
        if hasattr(row_node, "labels") and row_node.labels:
            label_str = row_node.labels[0]
        elif hasattr(row_node, "alias"):
            label_str = str(row_node.alias)
        if not label_str:
            label_str = props.pop("__label", "Function")
        try:
            label = NodeLabel(label_str)
        except ValueError:
            label = NodeLabel.FUNCTION
        return GraphNode(label=label, properties=props, uid=uid)

    async def find_node_by_path(self, repository: str, path: str) -> GraphNode | None:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (n:Module {repository: $repo, path: $path}) RETURN n LIMIT 1",
                params={"repo": repository, "path": path},
            ),
        )
        if not result.result_set:
            return None
        return self._row_to_graph_node(result.result_set[0][0])

    async def find_node_by_fqn(self, repository: str, fqn: str) -> GraphNode | None:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (n {repository: $repo}) WHERE n.fqn = $fqn RETURN n LIMIT 1",
                params={"repo": repository, "fqn": fqn},
            ),
        )
        if not result.result_set:
            return None
        return self._row_to_graph_node(result.result_set[0][0])

    async def find_children(self, repository: str, parent_uid: str) -> list[GraphNode]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (p {uid: $uid})-[:CONTAINS]->(c) "
                "WHERE c.repository = $repo "
                "RETURN c",
                params={"uid": parent_uid, "repo": repository},
            ),
        )
        nodes: list[GraphNode] = []
        for row in result.result_set or []:
            n = self._row_to_graph_node(row[0])
            if n is not None:
                nodes.append(n)
        return nodes

    async def find_descendants(
        self, uid: str, *, edge_type: str = "CONTAINS", max_depth: int = 3
    ) -> list[str]:
        """Return UIDs of all descendants reachable via edge_type up to max_depth."""
        if edge_type not in self._ALLOWED_EDGE_TYPES:
            raise ValueError(f"Edge type '{edge_type}' not allowed for traversal")
        max_depth = max(1, min(max_depth, 10))
        loop = asyncio.get_running_loop()
        query = (
            f"MATCH (root {{uid: $uid}})-[:{edge_type}*1..{max_depth}]->(desc) "
            f"RETURN DISTINCT desc.uid AS uid"
        )
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(query, params={"uid": uid}),  # type: ignore[union-attr]
        )
        return [row[0] for row in (result.result_set or []) if row[0]]

    async def find_top_level_modules(self, repository: str) -> list[GraphNode]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (m:Module {repository: $repo}) "
                "WHERE NOT ()-[:CONTAINS]->(m) "
                "RETURN m",
                params={"repo": repository},
            ),
        )
        nodes: list[GraphNode] = []
        for row in result.result_set or []:
            n = self._row_to_graph_node(row[0])
            if n is not None:
                nodes.append(n)
        return nodes

    async def list_repository_modules(self, repository: str) -> list[GraphNode]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (m:Module {repository: $repo}) RETURN m",
                params={"repo": repository},
            ),
        )
        nodes: list[GraphNode] = []
        for row in result.result_set or []:
            n = self._row_to_graph_node(row[0])
            if n is not None:
                nodes.append(n)
        return nodes

    async def find_module_import_edges(self, repository: str) -> list[GraphEdge]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (a:Module {repository: $repo})-[r:IMPORTS]->(b:Module) "
                "RETURN a.uid AS src, b.uid AS tgt, type(r) AS rtype",
                params={"repo": repository},
            ),
        )
        edges: list[GraphEdge] = []
        for row in result.result_set or []:
            edges.append(GraphEdge(
                edge_type=EdgeType.IMPORTS,
                source_uid=str(row[0]),
                target_uid=str(row[1]),
            ))
        return edges

    async def find_repository_calls_edges(self, repository: str) -> list[GraphEdge]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (a {repository: $repo})-[r:CALLS]->(b) "
                "RETURN a.uid AS src, b.uid AS tgt",
                params={"repo": repository},
            ),
        )
        edges: list[GraphEdge] = []
        for row in result.result_set or []:
            edges.append(GraphEdge(
                edge_type=EdgeType.CALLS,
                source_uid=str(row[0]),
                target_uid=str(row[1]),
            ))
        return edges

    async def find_all_referrers_batch(self, repository: str) -> dict[str, list[str]]:
        """Batch-load all CALLS/IMPORTS relationships for backlink building.

        Returns ``{target_uid: [source_uid, ...]}`` for edges where both endpoints
        belong to the given repository.
        """
        q = (
            "MATCH (src)-[:CALLS|IMPORTS]->(tgt) "
            "WHERE src.repository = $repo AND tgt.repository = $repo "
            "RETURN tgt.uid, src.uid"
        )
        result = await self.execute_query(q, {"repo": repository})
        referrers: dict[str, list[str]] = {}
        for row in result.raw or []:
            if not row:
                continue
            tgt_uid, src_uid = row[0], row[1]
            if tgt_uid is not None and src_uid is not None:
                ts, ss = str(tgt_uid), str(src_uid)
                if ts and ss:
                    referrers.setdefault(ts, []).append(ss)
        return referrers

    async def find_edges(self, repository: str, node_uid: str) -> list[GraphEdge]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (a {uid: $uid})-[r]->(b) "
                "RETURN a.uid AS src, b.uid AS tgt, type(r) AS rtype "
                "UNION "
                "MATCH (a)-[r]->(b {uid: $uid}) "
                "RETURN a.uid AS src, b.uid AS tgt, type(r) AS rtype",
                params={"uid": node_uid},
            ),
        )
        edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for row in result.result_set or []:
            src, tgt, rtype = str(row[0]), str(row[1]), str(row[2])
            key = (src, tgt, rtype)
            if key in seen:
                continue
            seen.add(key)
            try:
                edge_type = EdgeType(rtype)
            except ValueError:
                continue
            edges.append(GraphEdge(edge_type=edge_type, source_uid=src, target_uid=tgt))
        return edges

    async def find_node_by_uid(self, repository: str, uid: str) -> GraphNode | None:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(  # type: ignore[union-attr]
                "MATCH (n {uid: $uid}) RETURN n LIMIT 1",
                params={"uid": uid},
            ),
        )
        if not result.result_set:
            return None
        return self._row_to_graph_node(result.result_set[0][0])

    @property
    def graph(self) -> Graph | None:
        return self._graph
