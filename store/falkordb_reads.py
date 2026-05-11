from __future__ import annotations

import asyncio
from typing import Any

from core.log import get_logger
from store.falkordb_common import REFERENCES_CROSS_FILE_CYPHER, _graph_executor, _xref_lock

from .schema import EdgeType, GraphEdge, GraphNode, NodeLabel

log = get_logger("store.falkordb_store")


class FalkorDBReadsMixin:
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

    async def resolve_cross_file_edges(self) -> dict[str, int]:
        """Rebuild INHERITS, IMPORTS, and REFERENCES edges via name-based matching.

        Deletes stale auto-resolved edges first, then recreates from current data.
        This ensures renamed/deleted entities don't leave orphan edges.
        """
        async with _xref_lock:
            loop = asyncio.get_running_loop()
            stats: dict[str, int] = {}

            for edge_type in ("INHERITS", "REFERENCES"):
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

    async def get_repo_stats(self, repository: str) -> dict[str, int]:
        """Return entity counts per label for a repository."""
        loop = asyncio.get_running_loop()
        counts: dict[str, int] = {"module_count": 0, "class_count": 0, "function_count": 0}
        for label_name, key in [
            ("Module", "module_count"),
            ("Class", "class_count"),
            ("Function", "function_count"),
        ]:
            query = f"MATCH (n:{label_name} {{repository: $repo}}) RETURN count(n) AS cnt"
            try:
                result = await loop.run_in_executor(
                    _graph_executor,
                    lambda q=query: self._graph.query(q, params={"repo": repository}),  # type: ignore[union-attr]
                )
                if result.result_set:
                    counts[key] = result.result_set[0][0]
            except Exception:
                log.debug(
                    "get_repo_stats_query_failed",
                    label=label_name,
                    repository=repository,
                    exc_info=True,
                )
        return counts

    async def find_related_entities(
        self,
        uid: str,
        *,
        edge_types: list[str] | None = None,
        max_hops: int = 1,
    ) -> list[tuple[str, str]]:
        """Find entities related via specified edge types (bidirectional). Returns (uid, edge_type) pairs.

        When ``edge_types`` is omitted or empty, defaults to RELATED_TO only (avoids matching every edge).
        Results are deduplicated by neighbor uid (first edge type retained).
        """
        _ = max_hops  # single-hop match; parameter reserved for API evolution
        loop = asyncio.get_running_loop()
        effective_types = edge_types if edge_types else ["RELATED_TO"]
        invalid = set(effective_types) - self._ALLOWED_RELATED_EDGE_TYPES
        if invalid:
            raise ValueError(f"Edge types not allowed: {invalid}")
        et_list = "|".join(effective_types)
        et_filter = f":{et_list}"

        query_out = (
            f"MATCH (a {{uid: $uid}})-[r{et_filter}]->(b) "
            f"RETURN b.uid AS uid, type(r) AS etype"
        )
        query_in = (
            f"MATCH (a {{uid: $uid}})<-[r{et_filter}]-(b) "
            f"RETURN b.uid AS uid, type(r) AS etype"
        )
        results: list[tuple[str, str]] = []
        for q in (query_out, query_in):
            try:
                res = await loop.run_in_executor(
                    _graph_executor,
                    lambda query=q: self._graph.query(query, params={"uid": uid}),  # type: ignore[union-attr]
                )
                for row in (res.result_set or []):
                    if row[0] and row[0] != uid:
                        results.append((row[0], row[1]))
            except Exception:
                log.debug("find_related_entities_query_failed", uid=uid, exc_info=True)
        seen: set[str] = set()
        deduped: list[tuple[str, str]] = []
        for uid_val, etype in results:
            if uid_val not in seen:
                seen.add(uid_val)
                deduped.append((uid_val, etype))
        return deduped

    async def find_entities_by_domain(
        self,
        domain: str,
        *,
        exclude_uid: str = "",
        limit: int = 20,
    ) -> list[str]:
        """Find entity UIDs with matching business_domain property."""
        loop = asyncio.get_running_loop()
        query = (
            "MATCH (n {business_domain: $domain}) "
            "WHERE n.uid <> $exclude "
            "RETURN n.uid AS uid LIMIT $limit"
        )
        try:
            result = await loop.run_in_executor(
                _graph_executor,
                lambda: self._graph.query(  # type: ignore[union-attr]
                    query,
                    params={"domain": domain, "exclude": exclude_uid, "limit": limit},
                ),
            )
            return [row[0] for row in (result.result_set or []) if row[0]]
        except Exception:
            log.debug("find_entities_by_domain_failed", domain=domain, exc_info=True)
            return []

    async def find_siblings(self, uid: str) -> list[str]:
        """Find sibling entities under the same CONTAINS parent."""
        loop = asyncio.get_running_loop()
        query = (
            "MATCH (parent)-[:CONTAINS]->(me {uid: $uid}) "
            "MATCH (parent)-[:CONTAINS]->(sibling) "
            "WHERE sibling.uid <> $uid "
            "RETURN DISTINCT sibling.uid AS uid LIMIT 20"
        )
        try:
            result = await loop.run_in_executor(
                _graph_executor,
                lambda: self._graph.query(query, params={"uid": uid}),  # type: ignore[union-attr]
            )
            return [row[0] for row in (result.result_set or []) if row[0]]
        except Exception:
            log.debug("find_siblings_failed", uid=uid, exc_info=True)
            return []

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
