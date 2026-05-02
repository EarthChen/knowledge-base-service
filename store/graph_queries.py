"""Centralized graph query layer.

All Cypher queries used by API endpoints are defined here,
providing a single point of maintenance for the query vocabulary.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from log import get_logger
from services.repo_registry import RepoRegistry

log = get_logger(__name__)

# Disallow characters that are unsafe or meaningless for parameterized class-name search.
_ARCHITECTURE_CLASS_SEARCH_DISALLOWED = re.compile(r'[`"\';\\#\x00-\x1f]')


def validate_architecture_class_search(search: str | None) -> str | None:
    """Validate optional search text for architecture class listing; return trimmed value or None."""
    if search is None:
        return None
    s = search.strip()
    if not s:
        return None
    if len(s) > 500:
        raise ValueError("search must be at most 500 characters")
    if _ARCHITECTURE_CLASS_SEARCH_DISALLOWED.search(s):
        raise ValueError("search contains disallowed characters")
    return s

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

    async def tag_unowned_nodes(
        self,
        repository: str,
        directory: str | None = None,
        git_url: str | None = None,
        file_prefix: str | None = None,
    ) -> None:
        """Assign repository to nodes that still lack one (narrow backfill only).

        Prefer setting ``repository`` during indexing; this must not scan the whole graph
        for relative paths — that races when multiple repos index concurrently.

        * ``directory`` — match only ``n.file`` under this absolute path prefix.
        * ``file_prefix`` — optional extra match for repo-relative paths (e.g. a submodule folder).
        """
        git_key = RepoRegistry._normalize_key(git_url) if git_url else None
        if git_key is not None:
            set_clause = "SET n.repository = $repo, n.git_url = $gurl"
            base_params: dict[str, Any] = {"repo": repository, "gurl": git_key}
        else:
            set_clause = "SET n.repository = $repo"
            base_params = {"repo": repository}

        where_base = "MATCH (n) WHERE n.repository IS NULL AND "

        if directory:
            dir_prefix = Path(directory).resolve().as_posix().rstrip("/") + "/"
            await self._store.execute_query(
                where_base + "n.file STARTS WITH $dir_prefix " + set_clause,
                {**base_params, "dir_prefix": dir_prefix},
            )
            await self._store.execute_query(
                "MATCH (n:Module) WHERE n.repository IS NULL AND n.path STARTS WITH $dir_prefix "
                + set_clause,
                {**base_params, "dir_prefix": dir_prefix},
            )

        if file_prefix:
            fp = file_prefix.replace("\\", "/").strip().rstrip("/") + "/"
            await self._store.execute_query(
                where_base + "n.file STARTS WITH $file_prefix " + set_clause,
                {**base_params, "file_prefix": fp},
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
            "RETURN n.repository AS repo, count(n) AS cnt, max(n.git_url) AS git_url "
            "ORDER BY cnt DESC",
        )
        rows = []
        for r in result.data:
            row: dict[str, Any] = {"repository": r["repo"], "nodes": r["cnt"]}
            gu = r.get("git_url")
            if gu:
                row["git_url"] = gu
            rows.append(row)
        return rows

    async def find_repository_by_git_url(self, git_url: str) -> str | None:
        """Return a repository name if any indexed node carries this URL key."""
        key = RepoRegistry._normalize_key(git_url)
        result = await self._store.execute_query(
            "MATCH (n) WHERE n.git_url = $key AND n.repository IS NOT NULL "
            "RETURN n.repository AS repo LIMIT 1",
            {"key": key},
        )
        if not result.data:
            return None
        repo = result.data[0].get("repo")
        return str(repo) if repo is not None else None

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

    async def get_knowledge_health_stats(self) -> dict[str, Any]:
        """Coverage, staleness, orphan ratio, and graph size for the health dashboard."""

        def _parse_ts(value: Any) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            if isinstance(value, (int, float)):
                ts = float(value)
                if ts > 1e12:
                    ts /= 1000.0
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            s = str(value).strip()
            if not s:
                return None
            try:
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                dt = datetime.fromisoformat(s)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return None

        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=7)

        cnt_nodes = await self._store.execute_query("MATCH (n) RETURN count(n) AS c")
        total_nodes = int(cnt_nodes.data[0].get("c") or 0) if cnt_nodes.data else 0

        cnt_edges = await self._store.execute_query("MATCH ()-[r]->() RETURN count(r) AS c")
        total_edges = int(cnt_edges.data[0].get("c") or 0) if cnt_edges.data else 0

        orphan_q = await self._store.execute_query(
            "MATCH (n) WHERE NOT (n)-[]-() RETURN count(n) AS c"
        )
        orphan_count = int(orphan_q.data[0].get("c") or 0) if orphan_q.data else 0
        orphan_ratio = (orphan_count / total_nodes) if total_nodes > 0 else 0.0

        repo_rows = await self._store.execute_query(
            "MATCH (n) WHERE n.repository IS NOT NULL "
            "RETURN n.repository AS repo, max(n.indexed_at) AS last_idx"
        )

        total_repos = 0
        recent_repos = 0
        for row in repo_rows.data:
            total_repos += 1
            last_idx = _parse_ts(row.get("last_idx"))
            if last_idx is not None and last_idx >= recent_cutoff:
                recent_repos += 1

        if total_repos > 0:
            index_coverage = recent_repos / total_repos
        else:
            index_coverage = 1.0

        global_q = await self._store.execute_query(
            "MATCH (n) WHERE n.indexed_at IS NOT NULL RETURN max(n.indexed_at) AS mx"
        )
        global_max = _parse_ts(global_q.data[0].get("mx")) if global_q.data else None

        last_indexed_at: str | None = None
        staleness_hours: float | None = None
        if global_max is not None:
            last_indexed_at = global_max.isoformat().replace("+00:00", "Z")
            staleness_hours = max(0.0, (now - global_max).total_seconds() / 3600.0)

        return {
            "index_coverage": round(float(index_coverage), 4),
            "staleness_hours": round(float(staleness_hours), 2) if staleness_hours is not None else None,
            "orphan_ratio": round(float(orphan_ratio), 4),
            "last_indexed_at": last_indexed_at,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
        }

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
            "coalesce(n.fqn, '') AS fqn, labels(n)[0] AS type, "
            "n.commit_sha AS commit_sha, n.indexed_at AS indexed_at",
            {"uid": node_uid},
        )
        return result.data[0] if result.data else None

    async def count_classes_by_architecture_layer(
        self,
        layer: str,
        repository: str | None = None,
        search: str | None = None,
    ) -> int:
        """Count Class nodes in an architecture layer (no method expansion)."""
        params: dict[str, Any] = {"layer": layer}
        repo_clause = ""
        if repository:
            repo_clause = "AND c.repository = $repo "
            params["repo"] = repository
        search_clause = ""
        search_norm = search.lower().strip() if search else ""
        if search_norm:
            search_clause = "AND toLower(c.name) CONTAINS $search "
            params["search"] = search_norm

        cypher = (
            "MATCH (c:Class) "
            "WHERE c.architecture_layer = $layer " + repo_clause + search_clause +
            "RETURN count(c) AS cnt"
        )
        result = await self._store.execute_query(cypher, params)
        row = result.data[0] if result.data else {}
        cnt = row.get("cnt")
        return int(cnt) if cnt is not None else 0

    async def search_classes_by_architecture_layer(
        self,
        layer: str,
        repository: str | None,
        limit: int,
        *,
        search: str | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return Class nodes in an architecture layer with contained methods."""
        params: dict[str, Any] = {"layer": layer, "limit": limit, "offset": offset}
        repo_clause = ""
        if repository:
            repo_clause = "AND c.repository = $repo "
            params["repo"] = repository
        search_clause = ""
        search_norm = search.lower().strip() if search else ""
        if search_norm:
            search_clause = "AND toLower(c.name) CONTAINS $search "
            params["search"] = search_norm

        cypher = (
            "MATCH (c:Class) "
            "WHERE c.architecture_layer = $layer " + repo_clause + search_clause +
            "WITH c ORDER BY coalesce(c.fqn, c.name) "
            "SKIP $offset LIMIT $limit "
            "OPTIONAL MATCH (c)-[:CONTAINS]->(m:Function) "
            "WITH c, m ORDER BY m.name LIMIT 2000 "
            "RETURN c.uid AS uid, c.name AS name, c.fqn AS fqn, c.file AS file, "
            "c.repository AS repository, c.semantic_roles AS semantic_roles, "
            "c.architecture_layer AS architecture_layer, "
            "m.uid AS m_uid, m.name AS m_name, m.signature AS m_signature, m.fqn AS m_fqn"
        )
        result = await self._store.execute_query(cypher, params)
        by_uid: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for row in result.data:
            uid = row.get("uid") or ""
            if not uid:
                continue
            if uid not in by_uid:
                order.append(uid)
                by_uid[uid] = {
                    "uid": uid,
                    "name": row.get("name"),
                    "fqn": row.get("fqn"),
                    "file": row.get("file"),
                    "repository": row.get("repository"),
                    "semantic_roles": row.get("semantic_roles"),
                    "architecture_layer": row.get("architecture_layer"),
                    "methods": [],
                }
            m_uid = row.get("m_uid")
            if m_uid:
                by_uid[uid]["methods"].append({
                    "uid": m_uid,
                    "name": row.get("m_name"),
                    "signature": row.get("m_signature") or "",
                    "fqn": row.get("m_fqn") or "",
                })
        return [by_uid[u] for u in order if u in by_uid]

    async def get_enrichable_entities(
        self, repository: str | None, force: bool,
    ) -> list[dict[str, Any]]:
        """查询待 LLM 摘要的 Function/Class 行（可选仓库；force 为假时仅缺 business_summary）。"""
        if force:
            missing_filter = ""
        else:
            missing_filter = (
                "AND (NOT exists(n.business_summary) OR n.business_summary = '')"
            )

        if repository:
            cypher = (
                "MATCH (n) "
                "WHERE (n:Function OR n:Class) AND n.repository = $repo "
                f"{missing_filter} "
                "RETURN n.name AS name, coalesce(n.signature, '') AS signature, "
                "coalesce(n.docstring, '') AS docstring, coalesce(n.code_snippet, '') AS code_snippet, "
                "coalesce(n.file, '') AS file, labels(n)[0] AS label, n.uid AS uid"
            )
            params: dict[str, Any] = {"repo": repository}
        else:
            cypher = (
                "MATCH (n) "
                f"WHERE (n:Function OR n:Class) {missing_filter} "
                "RETURN n.name AS name, coalesce(n.signature, '') AS signature, "
                "coalesce(n.docstring, '') AS docstring, coalesce(n.code_snippet, '') AS code_snippet, "
                "coalesce(n.file, '') AS file, labels(n)[0] AS label, n.uid AS uid"
            )
            params = {}

        result = await self._store.execute_query(cypher, params)
        return result.data

    # ── Graph exploration ───────────────────────────────────────

    async def explore_overview(self, limit: int) -> QueryResultWrapper:
        overview_q = (
            "MATCH (n) "
            "WHERE n:Function OR n:Class OR n:Module "
            "WITH n, rand() AS r ORDER BY r LIMIT $limit "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, "
            "coalesce(n.file, '') AS file, coalesce(n.start_line, 0) AS line, "
            "coalesce(n.end_line, n.start_line, 0) AS end_line, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring"
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
            "coalesce(n.file, '') AS file, coalesce(n.start_line, 0) AS line, "
            "coalesce(n.end_line, n.start_line, 0) AS end_line, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring"
        )
        return await self._store.execute_query(nodes_q, {"name": name, "limit": limit})

    async def explore_by_uid(self, uid: str, depth: int, limit: int) -> QueryResultWrapper:
        """Like ``explore_by_name`` but centers on a node identified by graph ``uid``."""
        nodes_q = (
            "MATCH (center) "
            "WHERE (center:Function OR center:Class OR center:Module) "
            "AND center.uid = $uid "
            f"OPTIONAL MATCH (center)-[*1..{depth}]-(neighbor) "
            "WHERE neighbor:Function OR neighbor:Class OR neighbor:Module "
            "WITH center, collect(DISTINCT neighbor) AS nbrs "
            "UNWIND ([center] + nbrs) AS n "
            "WITH DISTINCT n LIMIT $limit "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, "
            "coalesce(n.file, '') AS file, coalesce(n.start_line, 0) AS line, "
            "coalesce(n.end_line, n.start_line, 0) AS end_line, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring"
        )
        return await self._store.execute_query(nodes_q, {"uid": uid, "limit": limit})

    async def explore_edges(self, node_uids: list[str]) -> QueryResultWrapper:
        edges_q = (
            "MATCH (a)-[rel]->(b) "
            "WHERE a.uid IN $uids AND b.uid IN $uids "
            "RETURN a.uid AS source, b.uid AS target, type(rel) AS rel_type"
        )
        return await self._store.execute_query(edges_q, {"uids": node_uids})

    async def shortest_path_between_names(
        self,
        repository: str,
        from_name: str,
        to_name: str,
        *,
        max_depth: int = 5,
    ) -> dict[str, Any]:
        """Find shortest path between two named entities using shortestPath with fallback."""
        rel = "CALLS|INHERITS|IMPORTS"
        d = min(max(1, int(max_depth)), 8)
        primary = (
            f"MATCH (a), (b) "
            f"WHERE a.repository = $repo AND b.repository = $repo "
            f"AND (a.name = $from OR a.fqn = $from) AND (b.name = $to OR b.fqn = $to) "
            f"MATCH p = shortestPath((a)-[:{rel}*1..{d}]-(b)) "
            f"RETURN p, length(p) AS depth, "
            f"[n IN nodes(p) | coalesce(n.name, n.fqn, '')] AS nodes, "
            f"[r IN relationships(p) | type(r)] AS rels LIMIT 1"
        )
        params = {"repo": repository, "from": from_name, "to": to_name}
        try:
            res = await self._store.execute_query(primary, params)
            rows = getattr(res, "data", None) or []
            if rows:
                return {"ok": True, "rows": rows, "used": "shortestPath"}
        except Exception:
            log.debug("shortest_path_primary_query_failed", exc_info=True)
        fb = (
            f"MATCH (a), (b) "
            f"WHERE a.repository = $repo AND b.repository = $repo "
            f"AND (a.name = $from OR a.fqn = $from) AND (b.name = $to OR b.fqn = $to) "
            f"MATCH path = (a)-[*1..{d}]-(b) "
            f"RETURN path, length(path) AS depth, "
            f"[n IN nodes(path) | coalesce(n.name, n.fqn, '')] AS nodes, "
            f"[r IN relationships(path) | type(r)] AS rels "
            f"ORDER BY depth LIMIT 1"
        )
        res2 = await self._store.execute_query(fb, params)
        rows2 = getattr(res2, "data", None) or []
        return {"ok": bool(rows2), "rows": rows2, "used": "variable_length_fallback"}

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
