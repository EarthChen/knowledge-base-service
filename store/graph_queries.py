"""Centralized graph query layer.

All Cypher queries used by API endpoints are defined here,
providing a single point of maintenance for the query vocabulary.
"""

from __future__ import annotations

from typing import Any

from .falkordb_store import FalkorDBStore, QueryResultWrapper


class GraphQueryRepository:
    """Encapsulates all business-level graph queries."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def execute_raw(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
        """Escape hatch for ad-hoc Cypher — prefer adding a named method instead."""
        return await self._store.execute_query(cypher, params)

    # ── Repository management ───────────────────────────────────

    async def tag_nodes_with_repository(self, file_path: str, repository: str) -> None:
        await self._store.execute_query(
            "MATCH (n) WHERE n.file = $file SET n.repository = $repo",
            {"file": file_path, "repo": repository},
        )

    async def tag_unowned_nodes(self, repository: str, directory: str | None = None) -> None:
        """Assign repository to nodes that don't have one yet.

        Supports both absolute-path (STARTS WITH $dir) and
        relative-path (NOT STARTS WITH '/') scoping.
        """
        if directory:
            await self._store.execute_query(
                "MATCH (n) WHERE n.repository IS NULL AND "
                "(n.file STARTS WITH $dir OR NOT n.file STARTS WITH '/') "
                "SET n.repository = $repo",
                {"dir": directory, "repo": repository},
            )
        else:
            await self._store.execute_query(
                "MATCH (n) WHERE n.repository IS NULL AND NOT n.file STARTS WITH '/' "
                "SET n.repository = $repo",
                {"repo": repository},
            )

    async def get_repository_node_count(self, repository: str) -> int:
        result = await self._store.execute_query(
            "MATCH (n) WHERE n.repository = $repo RETURN count(n) AS cnt",
            {"repo": repository},
        )
        return result.data[0]["cnt"] if result.data else 0

    async def list_repositories(self) -> list[dict[str, Any]]:
        result = await self._store.execute_query(
            "MATCH (n) WHERE n.repository IS NOT NULL "
            "RETURN n.repository AS repo, count(n) AS cnt "
            "ORDER BY cnt DESC",
        )
        return [{"repository": r["repo"], "nodes": r["cnt"]} for r in result.data]

    async def list_repositories_with_samples(self) -> list[dict[str, Any]]:
        result = await self._store.execute_query(
            "MATCH (n) WHERE n.repository IS NOT NULL "
            "RETURN DISTINCT n.repository AS repo, collect(DISTINCT n.file)[0] AS sample_file",
        )
        return result.data

    async def list_repositories_with_multiple_samples(self) -> list[dict[str, Any]]:
        result = await self._store.execute_query(
            "MATCH (n) WHERE n.repository IS NOT NULL "
            "RETURN DISTINCT n.repository AS repo, collect(DISTINCT n.file)[0..3] AS samples",
        )
        return result.data

    async def get_repository_sample_file(self, repository: str) -> str | None:
        result = await self._store.execute_query(
            "MATCH (n {repository: $repo}) RETURN DISTINCT n.file AS file LIMIT 1",
            {"repo": repository},
        )
        if not result.data:
            return None
        return result.data[0].get("file") or None

    async def delete_repository(self, repository: str) -> int:
        result = await self._store.execute_query(
            "MATCH (n) WHERE n.repository = $repo DETACH DELETE n RETURN count(n) AS deleted",
            {"repo": repository},
        )
        return result.data[0]["deleted"] if result.data else 0

    # ── Document queries ────────────────────────────────────────

    async def list_documents(self, repository: str | None = None) -> QueryResultWrapper:
        base_cypher = (
            "MATCH (n:Document)-[:CONTAINS]->(sec:Document) "
            "{where_clause}"
            "RETURN n.uid AS uid, n.name AS name, n.file AS file, n.title AS title, "
            "n.repository AS repository, n.content_hash AS content_hash, "
            "sec.uid AS sec_uid, sec.name AS sec_name, sec.title AS sec_title, "
            "sec.start_line AS sec_start_line "
            "ORDER BY n.file, sec.start_line"
        )
        if repository:
            cypher = base_cypher.format(where_clause="WHERE n.repository = $repo ")
            params: dict[str, Any] = {"repo": repository}
        else:
            cypher = base_cypher.format(where_clause="")
            params = {}
        return await self._store.execute_query(cypher, params)

    async def get_document(self, doc_uid: str) -> QueryResultWrapper:
        cypher = (
            "MATCH (doc:Document {uid: $uid})-[:CONTAINS]->(section:Document) "
            "RETURN doc.title AS title, doc.file AS file, doc.repository AS repository, "
            "section.uid AS section_uid, section.name AS section_name, "
            "section.title AS section_title, section.content AS content, "
            "section.start_line AS start_line, section.level AS level "
            "ORDER BY section.start_line"
        )
        return await self._store.execute_query(cypher, {"uid": doc_uid})

    # ── Code snippet ────────────────────────────────────────────

    async def get_code_snippet(self, node_uid: str) -> dict[str, Any] | None:
        result = await self._store.execute_query(
            "MATCH (n {uid: $uid}) "
            "RETURN n.name AS name, n.file AS file, n.start_line AS start_line, "
            "n.end_line AS end_line, coalesce(n.code_snippet, '') AS code_snippet, "
            "coalesce(n.signature, '') AS signature, coalesce(n.docstring, '') AS docstring, "
            "coalesce(n.fqn, '') AS fqn, labels(n)[0] AS type",
            {"uid": node_uid},
        )
        return result.data[0] if result.data else None

    # ── Graph exploration ───────────────────────────────────────

    async def explore_overview(self, limit: int) -> QueryResultWrapper:
        overview_q = (
            "MATCH (n) "
            "WHERE n:Function OR n:Class OR n:Module "
            "WITH n, rand() AS r ORDER BY r LIMIT $limit "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, "
            "n.file AS file, n.start_line AS line"
        )
        return await self._store.execute_query(overview_q, {"limit": limit})

    async def explore_by_name(self, name: str, depth: int, limit: int) -> QueryResultWrapper:
        nodes_q = (
            "MATCH (center) "
            "WHERE (center:Function OR center:Class OR center:Module) "
            "AND (center.name = $name OR center.fqn = $name) "
            f"OPTIONAL MATCH (center)-[*1..{depth}]-(neighbor) "
            "WHERE neighbor:Function OR neighbor:Class OR neighbor:Module "
            "WITH center, collect(DISTINCT neighbor) AS nbrs "
            "UNWIND ([center] + nbrs) AS n "
            "WITH DISTINCT n LIMIT $limit "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, "
            "n.file AS file, n.start_line AS line"
        )
        return await self._store.execute_query(nodes_q, {"name": name, "limit": limit})

    async def explore_edges(self, node_uids: list[str]) -> QueryResultWrapper:
        edges_q = (
            "MATCH (a)-[rel]->(b) "
            "WHERE a.uid IN $uids AND b.uid IN $uids "
            "RETURN a.uid AS source, b.uid AS target, type(rel) AS rel_type"
        )
        return await self._store.execute_query(edges_q, {"uids": node_uids})

    # ── Admin operations ────────────────────────────────────────

    async def cleanup_excluded_dirs(self, patterns: list[str]) -> int:
        total = 0
        for pattern in patterns:
            result = await self._store.execute_query(
                "MATCH (n) WHERE n.file CONTAINS $pat DETACH DELETE n RETURN count(n) AS deleted",
                {"pat": f"/{pattern}/"},
            )
            count = result.data[0]["deleted"] if result.data else 0
            total += count
        return total

    async def backfill_fqn_candidates(self) -> list[dict[str, Any]]:
        result = await self._store.execute_query(
            "MATCH (n) WHERE (n:Class OR n:Function) AND n.file ENDS WITH '.java' "
            "AND n.fqn IS NULL "
            "RETURN n.uid AS uid, n.name AS name, n.file AS file, labels(n)[0] AS label",
        )
        return result.data

    async def get_function_parent_class(self, func_uid: str) -> str | None:
        result = await self._store.execute_query(
            "MATCH (c:Class)-[:CONTAINS]->(f:Function {uid: $uid}) RETURN c.name AS cname LIMIT 1",
            {"uid": func_uid},
        )
        return result.data[0].get("cname", "") if result.data else None

    async def set_node_fqn(self, uid: str, fqn: str) -> None:
        await self._store.execute_query(
            "MATCH (n {uid: $uid}) SET n.fqn = $fqn",
            {"uid": uid, "fqn": fqn},
        )

    # ── Migration ───────────────────────────────────────────────

    async def count_nodes_with_prefix(self, repository: str, prefix: str) -> int:
        result = await self._store.execute_query(
            "MATCH (n) WHERE n.repository = $repo AND n.file STARTS WITH $prefix "
            "RETURN count(n) AS cnt",
            {"repo": repository, "prefix": prefix},
        )
        return result.data[0]["cnt"] if result.data else 0

    async def migrate_file_paths(self, repository: str, prefix: str) -> None:
        await self._store.execute_query(
            "MATCH (n) WHERE n.repository = $repo AND n.file STARTS WITH $prefix "
            "SET n.file = REPLACE(n.file, $prefix, ''), "
            "n.uid = REPLACE(n.uid, $prefix, '')",
            {"repo": repository, "prefix": prefix},
        )

    async def migrate_node_paths(self, repository: str, prefix: str) -> None:
        await self._store.execute_query(
            "MATCH (n) WHERE n.repository = $repo AND n.path IS NOT NULL AND n.path STARTS WITH $prefix "
            "SET n.path = REPLACE(n.path, $prefix, '')",
            {"repo": repository, "prefix": prefix},
        )
