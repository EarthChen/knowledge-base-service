"""Wiki page–oriented Cypher (search, CRUD, chunks, ask, entity link queries)."""

from __future__ import annotations

import difflib
import hashlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from store.falkordb_store import QueryResultWrapper
from store.schema import EdgeType, NodeLabel
from store.wiki_store_common import SOURCE_DOC_EDGE, _wiki_node_properties


class WikiPageStoreMixin:
    """Page CRUD, search, and related query helpers. Expects ``self._store: _GraphQueryPort``."""

    async def update_node_property(
        self, label: NodeLabel, uid: str, prop: str, value: object
    ) -> None:
        """Persist a whitelisted node property via the underlying FalkorDB store."""
        updater = getattr(self._store, "update_node_property", None)
        if updater is None:
            raise AttributeError("Base graph store does not implement update_node_property")
        await updater(label, uid, prop, value)

    # --- wiki/search.py ---
    async def neighbor_names(self, name: str) -> QueryResultWrapper:
        q = (
            "MATCH (n)-[:CALLS|INHERITS|IMPORTS]->(m) "
            "WHERE n.name = $name "
            "RETURN DISTINCT m.name AS neighbor LIMIT 5"
        )
        return await self._store.execute_query(q, {"name": name})

    async def graph_path_search(self, repository: str, terms: list[str], limit: int) -> QueryResultWrapper:
        q = (
            "UNWIND $terms AS term "
            "MATCH (seed)-[:CALLS|INHERITS|IMPORTS*1..3]-(related) "
            "WHERE (seed:Function OR seed:Class OR seed:Module) "
            "AND (seed.name = term OR seed.fqn = term OR seed.fqn ENDS WITH term) "
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository IN [$repository, 'default'] "
            "AND (wp.title CONTAINS related.name OR wp.content CONTAINS related.name) "
            "RETURN DISTINCT wp.path AS page_path, wp.title AS title, "
            "left(wp.content, 240) AS snippet "
            "LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"repository": repository, "terms": terms, "limit": limit},
        )

    async def fulltext_wiki_search(self, text: str, repository: str, limit: int) -> QueryResultWrapper:
        q = (
            "CALL db.idx.fulltext.queryNodes('WikiPage', $text) YIELD node, score "
            "WHERE node.repository IN [$repository, 'default'] "
            "RETURN node, score LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"text": text, "repository": repository, "limit": limit},
        )

    async def vector_wiki_search(self, k: int, vec: list[float], repository: str, limit: int) -> QueryResultWrapper:
        q = (
            "CALL db.idx.vector.queryNodes('WikiPage', 'embedding', $k, vecf32($vec)) "
            "YIELD node, score "
            "WHERE node.repository IN [$repository, 'default'] "
            "RETURN node, score LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"k": k, "vec": vec, "repository": repository, "limit": limit},
        )

    async def ensure_wiki_fulltext_index(self) -> QueryResultWrapper:
        return await self._store.execute_query(
            "CALL db.idx.fulltext.createNodeIndex('WikiPage', 'content', 'title')",
        )

    # --- wiki/lint.py ---
    async def list_wiki_pages_for_repo(self, repository: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repository}) "
            "RETURN coalesce(wp.uid, '') AS uid, wp.path AS path, "
            "wp.title AS title, wp.content AS content, "
            "coalesce(wp.page_type, '') AS page_type, "
            "coalesce(wp.generated_at, '') AS generated_at, "
            "coalesce(wp.referenced_entity_uids, []) AS referenced_entity_uids, "
            "wp.stability_factor AS stability_factor, "
            "coalesce(wp.last_accessed, '') AS last_accessed"
        )
        return await self._store.execute_query(q, {"repository": repository})

    async def lint_stale_entity_refs(self, repository: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repository}) "
            "UNWIND coalesce(wp.referenced_entity_uids, []) AS uid "
            "OPTIONAL MATCH (n) WHERE n.uid = uid "
            "WITH wp, uid, n WHERE n IS NULL AND uid <> '' "
            "RETURN DISTINCT wp.path AS page_path, uid AS stale_uid"
        )
        return await self._store.execute_query(q, {"repository": repository})

    async def count_wiki_pages_for_repository(self, repository: str) -> QueryResultWrapper:
        q = "MATCH (wp:WikiPage {repository: $repository}) RETURN count(wp) AS cnt"
        return await self._store.execute_query(q, {"repository": repository})

    async def entity_uid_by_fqn(self, repository: str, fqn: str) -> QueryResultWrapper:
        q = (
            "MATCH (n) WHERE n.repository = $repository AND n.fqn = $fqn "
            "RETURN n.uid AS uid LIMIT 1"
        )
        return await self._store.execute_query(q, {"repository": repository, "fqn": fqn})

    async def delete_broken_wiki_references(self, repository: str) -> int:
        """Delete WIKI_REFERENCES edges that point to missing or uid-less nodes."""
        q = (
            "MATCH (wp:WikiPage {repository: $repo})-[r:WIKI_REFERENCES]->(target) "
            "WHERE target IS NULL OR NOT EXISTS(target.uid) "
            "DELETE r RETURN count(r) AS cnt"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        rows = getattr(result, "data", []) or []
        if rows and isinstance(rows[0], dict):
            return rows[0].get("cnt", 0)
        return 0

    async def deprecate_orphan_wiki_pages(self, repository: str) -> int:
        """Mark WikiPages with no SOURCE_ENTITY relationship as deprecated."""
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE NOT (wp)-[:SOURCE_ENTITY]->() "
            "SET wp.deprecated = true "
            "RETURN count(wp) AS cnt"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        rows = getattr(result, "data", []) or []
        if rows and isinstance(rows[0], dict):
            return rows[0].get("cnt", 0)
        return 0

    async def wiki_orphan_in_degrees(self, repository: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repository}) "
            "OPTIONAL MATCH (src:WikiPage)-[:WIKILINK]->(wp) "
            "WITH wp, count(src) AS in_degree "
            "RETURN wp.path AS path, in_degree"
        )
        return await self._store.execute_query(q, {"repository": repository})

    async def lint_coverage_gaps(self, repository: str) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class) "
            "WHERE c.repository = $repository "
            "AND ("
            " 'service' IN coalesce(c.semantic_roles, []) OR "
            " 'http_controller' IN coalesce(c.semantic_roles, []) OR "
            " 'repository' IN coalesce(c.semantic_roles, [])"
            ") "
            "OPTIONAL MATCH (wp:WikiPage {repository: $repository}) "
            "WHERE wp.title = c.name OR wp.path ENDS WITH '/' + c.name + '.md' OR wp.path ENDS WITH c.name + '.md' "
            "WITH c, wp WHERE wp IS NULL "
            "RETURN coalesce(c.name, '') AS name, coalesce(c.fqn, '') AS fqn"
        )
        return await self._store.execute_query(q, {"repository": repository})

    # --- wiki/kb_wiki_pipeline.py ---
    async def get_wiki_page_repo_overview(self, repo: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repo, page_type: 'repo_overview'}) "
            "RETURN wp LIMIT 1"
        )
        return await self._store.execute_query(q, {"repo": repo})

    async def get_wiki_page_module(self, repo: str, slug: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE wp.page_type = 'module_overview' AND wp.path CONTAINS $slug "
            "RETURN wp LIMIT 1"
        )
        return await self._store.execute_query(q, {"repo": repo, "slug": slug})

    async def get_wiki_page_class(self, repo: str, name: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE wp.page_type = 'class_detail' AND (wp.title = $name OR wp.path CONTAINS $name) "
            "RETURN wp LIMIT 1"
        )
        return await self._store.execute_query(q, {"repo": repo, "name": name})

    async def list_wiki_pages_all(self, repo: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "RETURN wp.path AS path, wp.title AS title, wp.page_type AS page_type "
            "ORDER BY wp.path"
        )
        return await self._store.execute_query(q, {"repo": repo})

    async def list_wiki_pages_paginated(
        self, repository: str, skip: int = 0, limit: int = 50,
    ) -> tuple[QueryResultWrapper, int]:
        count_q = "MATCH (wp:WikiPage {repository: $repo}) RETURN count(wp) AS total"
        count_result = await self._store.execute_query(count_q, {"repo": repository})
        total = int(count_result.data[0]["total"]) if count_result.data else 0
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "RETURN wp.path AS path, wp.title AS title, wp.page_type AS page_type "
            "ORDER BY wp.path "
            "SKIP $skip "
            "LIMIT $limit"
        )
        result = await self._store.execute_query(
            q, {"repo": repository, "skip": skip, "limit": limit},
        )
        return result, total

    async def list_wiki_pages_module_prefix(self, repo: str, prefix: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE wp.path STARTS WITH $prefix "
            "RETURN wp.path AS path, wp.title AS title, wp.page_type AS page_type "
            "ORDER BY wp.path"
        )
        return await self._store.execute_query(q, {"repo": repo, "prefix": prefix})

    async def list_wiki_pages_class_contains(self, repo: str, name: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE wp.path CONTAINS $name "
            "RETURN wp.path AS path, wp.title AS title, wp.page_type AS page_type "
            "ORDER BY wp.path"
        )
        return await self._store.execute_query(q, {"repo": repo, "name": name})

    # --- wiki/doc_wiki_fusion.py ---
    async def find_related_docs_entities(self, entities: list[str], limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (d:Document)-[:REFERENCES]->(e) "
            "WHERE e.name IN $entities OR e.fqn IN $entities "
            "RETURN DISTINCT d.file AS file, d.content AS content "
            "LIMIT $limit"
        )
        return await self._store.execute_query(q, {"entities": entities, "limit": limit})

    async def merge_source_doc_edges_batch(
        self,
        repository: str,
        path: str,
        docs: list[str],
    ) -> QueryResultWrapper:
        q = (
            "UNWIND $docs AS doc_file "
            "MATCH (wp:WikiPage {repository: $repository, path: $path}) "
            "MATCH (d:Document) "
            "WHERE d.file = doc_file AND d.repository = $repository "
            f"MERGE (wp)-[:{SOURCE_DOC_EDGE}]->(d) "
            "RETURN count(*) AS cnt"
        )
        return await self._store.execute_query(
            q, {"repository": repository, "path": path, "docs": docs},
        )

    # --- wiki/ask.py (GraphEnhancedContextCollector) ---
    async def ask_query_wiki_pages(self, repository: str, paths: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository = $repository AND wp.path IN $paths "
            "RETURN wp.path AS page_path, wp.title AS title, wp.content AS content "
            "ORDER BY wp.path"
        )
        return await self._store.execute_query(q, {"repository": repository, "paths": paths})

    async def ask_query_one_hop(self, names: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (n)-[r:CALLS|INHERITS|IMPORTS]-(m) "
            "WHERE n.name IN $names "
            "RETURN type(r) AS rel_type, n.name AS from_name, m.name AS to_name LIMIT 25"
        )
        return await self._store.execute_query(q, {"names": names})

    async def ask_query_flow_callees(self, names: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (n) WHERE n.name IN $names "
            "MATCH path = (n)-[:CALLS*2..3]->(m) "
            "RETURN [x IN nodes(path) | coalesce(x.name, x.fqn, '')] AS chain LIMIT 15"
        )
        return await self._store.execute_query(q, {"names": names})

    async def ask_query_relation_paths(self, names: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (seed) WHERE seed.name IN $names AND (seed:Function OR seed:Class OR seed:Module) "
            "WITH collect(DISTINCT seed) AS seeds "
            "WHERE size(seeds) >= 2 "
            "WITH seeds[0] AS seed_a, seeds[-1] AS seed_b "
            "MATCH p = shortestPath((seed_a)-[:CALLS|INHERITS|IMPORTS*1..4]-(seed_b)) "
            "RETURN length(p) AS len, [x IN nodes(p) | coalesce(x.name, x.fqn, '')] AS path LIMIT 5"
        )
        return await self._store.execute_query(q, {"names": names})

    async def ask_query_shortest_path_between(
        self,
        repository: str,
        from_name: str,
        to_name: str,
        *,
        max_depth: int = 5,
    ) -> dict[str, Any]:
        """Repository-scoped shortest path; same logic as ``GraphQueryRepository.shortest_path_between_names``."""
        from store.graph_queries import GraphQueryRepository

        gq = GraphQueryRepository(self._store)
        return await gq.shortest_path_between_names(
            repository, from_name, to_name, max_depth=max_depth
        )

    async def ask_query_impact_callers(self, names: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (n) WHERE n.name IN $names "
            "MATCH path = (caller)-[:CALLS*1..3]->(n) "
            "RETURN DISTINCT caller.name AS caller LIMIT 25"
        )
        return await self._store.execute_query(q, {"names": names})

    async def ask_query_signatures(self, names: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (n) WHERE n.name IN $names AND (n:Function OR n:Class OR n:Method) "
            "RETURN n.name AS name, coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring LIMIT 20"
        )
        return await self._store.execute_query(q, {"names": names})

    async def ask_query_module_overview(self, repository: str, names: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (m:Module)-[:CONTAINS|DECLARED_IN*0..3]-(n) "
            "WHERE n.name IN $names AND m.repository = $repository "
            "RETURN coalesce(m.name, m.path, '') AS module, "
            "coalesce(m.summary, m.overview, '') AS overview LIMIT 8"
        )
        return await self._store.execute_query(
            q, {"repository": repository, "names": names},
        )

    # --- api/routes/wiki_routes.py ---
    async def list_all_wiki_pages(self, repository: str) -> QueryResultWrapper:
        return await self.list_wiki_pages_all(repository)

    async def get_wiki_page_detail(self, repository: str, path: str) -> QueryResultWrapper:
        q = "MATCH (wp:WikiPage {repository: $repo, path: $path}) RETURN wp LIMIT 1"
        return await self._store.execute_query(q, {"repo": repository, "path": path})

    async def get_related_entities(self, page_uid: str) -> list[dict[str, Any]]:
        """Get code entities linked to a wiki page via SOURCE_ENTITY edges."""
        _se = EdgeType.SOURCE_ENTITY.value
        q = (
            f"MATCH (wp:WikiPage {{uid: $uid}})-[:{_se}]->(e) "
            "WHERE e:Function OR e:Class OR e:Module "
            "RETURN coalesce(e.uid, '') AS uid, e.name AS name, labels(e) AS labels, "
            "coalesce(e.file, e.file_path, '') AS file_path, "
            "coalesce(e.start_line, 0) AS start_line, "
            "coalesce(e.signature, '') AS signature, "
            "coalesce(e.business_summary, e.docstring, '') AS business_summary, "
            "coalesce(e.repository, '') AS repository "
            "LIMIT 50"
        )
        result = await self._store.execute_query(q, {"uid": page_uid})
        return list(result.data) if result.data else []

    async def get_page_by_entity_uid(
        self, repository: str, entity_uid: str,
    ) -> SimpleNamespace | None:
        """Return persisted wiki page content for a code entity linked via SOURCE_ENTITY, if any."""
        pages = await self.get_pages_by_entity_uids(repository, [entity_uid])
        return pages.get(entity_uid)

    async def get_pages_by_entity_uids(
        self, repository: str, entity_uids: list[str], *, chunk_size: int = 500,
    ) -> dict[str, SimpleNamespace]:
        """Batch version of :meth:`get_page_by_entity_uid` keyed by entity UID."""
        if not entity_uids:
            return {}
        _se = EdgeType.SOURCE_ENTITY.value
        q = (
            f"UNWIND $entity_uids AS entity_uid "
            f"MATCH (wp:WikiPage {{repository: $repo}})-[:{_se}]->(e {{uid: entity_uid}}) "
            "RETURN entity_uid, coalesce(wp.content, '') AS content, "
            "coalesce(wp.path, '') AS path"
        )
        out: dict[str, SimpleNamespace] = {}
        uid_list = list(entity_uids)
        for i in range(0, len(uid_list), chunk_size):
            batch = uid_list[i : i + chunk_size]
            result = await self._store.execute_query(
                q, {"repo": repository, "entity_uids": batch},
            )
            for row in getattr(result, "data", None) or []:
                if not isinstance(row, dict):
                    continue
                eu = str(row.get("entity_uid") or "")
                if not eu:
                    continue
                out[eu] = SimpleNamespace(
                    content=str(row.get("content") or ""),
                    path=str(row.get("path") or ""),
                )
        return out

    async def get_wiki_page_navigation_row(
        self, repository: str, path: str,
    ) -> QueryResultWrapper:
        """Return persisted ``navigation_json`` for a wiki page (may be empty)."""
        q = (
            "MATCH (wp:WikiPage {repository: $repo, path: $path}) "
            "RETURN coalesce(wp.navigation_json, '') AS navigation_json LIMIT 1"
        )
        return await self._store.execute_query(q, {"repo": repository, "path": path})

    async def get_page_by_path(self, business_id: str, path: str) -> QueryResultWrapper:
        """Load one wiki page under a business WikiSpace by path, with aggregated SOURCE_ENTITY rows."""
        _se = EdgeType.SOURCE_ENTITY.value
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage {path: $path}) "
            f"OPTIONAL MATCH (wp)-[:{_se}]->(se) "
            "WITH wp, collect(DISTINCT {file_path: coalesce(se.file, se.file_path, ''), "
            "start_line: coalesce(se.start_line, 0), end_line: coalesce(se.end_line, 0), "
            "fqn: coalesce(se.fqn, ''), repository: coalesce(se.repository, ''), "
            "entity_uid: coalesce(se.uid, '')}) AS sources "
            "RETURN wp.path AS path, wp.title AS title, wp.content AS content, "
            "wp.page_type AS page_type, wp.importance_tier AS importance_tier, "
            "wp.repository AS repository, wp.uid AS uid, "
            "coalesce(wp.generated_at, '') AS generated_at, "
            "wp.confidence_score AS confidence_score, "
            "wp.quality_overall AS quality_overall, "
            "sources "
            "LIMIT 1"
        )
        return await self._store.execute_query(q, {"business_id": business_id, "path": path})

    async def get_page_by_repo_path(self, repository: str, path: str) -> QueryResultWrapper:
        """Direct repo-scoped page lookup, same return shape as ``get_page_by_path``."""
        _se = EdgeType.SOURCE_ENTITY.value
        q = (
            "MATCH (wp:WikiPage {repository: $repo, path: $path}) "
            f"OPTIONAL MATCH (wp)-[:{_se}]->(se) "
            "WITH wp, collect(DISTINCT {file_path: coalesce(se.file, se.file_path, ''), "
            "start_line: coalesce(se.start_line, 0), end_line: coalesce(se.end_line, 0), "
            "fqn: coalesce(se.fqn, ''), repository: coalesce(se.repository, ''), "
            "entity_uid: coalesce(se.uid, '')}) AS sources "
            "RETURN wp.path AS path, wp.title AS title, wp.content AS content, "
            "wp.page_type AS page_type, wp.importance_tier AS importance_tier, "
            "wp.repository AS repository, wp.uid AS uid, "
            "coalesce(wp.generated_at, '') AS generated_at, "
            "wp.confidence_score AS confidence_score, "
            "wp.quality_overall AS quality_overall, "
            "sources "
            "LIMIT 1"
        )
        return await self._store.execute_query(q, {"repo": repository, "path": path})

    async def get_page_stale_source_count(self, wiki_page_uid: str) -> int:
        """Count source entities indexed after the wiki page was generated (staleness heuristic)."""
        _se = EdgeType.SOURCE_ENTITY.value
        q = (
            f"MATCH (wp:WikiPage {{uid: $uid}})-[:{_se}]->(e) "
            "WHERE e.indexed_at > wp.generated_at "
            "RETURN count(e) AS stale_count LIMIT 1"
        )
        result = await self._store.execute_query(q, {"uid": wiki_page_uid})
        if result.data:
            return int(result.data[0].get("stale_count", 0))
        return 0

    # --- Phase 1: Code-aware queries ---

    async def find_chunks_by_parent_uid(self, parent_uid: str) -> QueryResultWrapper:
        """Find all Chunk nodes linked to a parent via PART_OF edge, ordered by chunk_index."""
        q = (
            "MATCH (c:Chunk)-[:PART_OF]->(p) "
            "WHERE p.uid = $parent_uid "
            "RETURN c.text AS text, c.file AS file, "
            "c.start_line AS start_line, c.end_line AS end_line, "
            "coalesce(c.chunk_index, 0) AS chunk_index "
            "ORDER BY chunk_index"
        )
        return await self._store.execute_query(q, {"parent_uid": parent_uid})

    async def score_all_entities(self, repository: str) -> QueryResultWrapper:
        """Single Cypher query to get degree data for all MODULE/CLASS nodes in a repository."""
        q = (
            "MATCH (n) WHERE n.repository = $repo AND (n:Module OR n:Class) "
            "OPTIONAL MATCH (n)<-[in_e]-() "
            "OPTIONAL MATCH (n)-[out_e]->() "
            "OPTIONAL MATCH (n)-[:CONTAINS]->(child) "
            "OPTIONAL MATCH (sub)-[:INHERITS]->(n) "
            "WITH n, labels(n)[0] AS label, "
            "count(DISTINCT in_e) AS in_degree, "
            "count(DISTINCT out_e) AS out_degree, "
            "count(DISTINCT child) AS children_count, "
            "count(DISTINCT sub) AS subclass_count "
            "OPTIONAL MATCH (caller)-[:CALLS]->(n) "
            "WHERE caller.business_domain IS NOT NULL "
            "RETURN n.uid AS uid, label, "
            "coalesce(n.start_line, 0) AS start_line, "
            "coalesce(n.end_line, 0) AS end_line, "
            "in_degree, out_degree, children_count, "
            "subclass_count, "
            "count(DISTINCT caller.business_domain) AS cross_domain_callers"
        )
        return await self._store.execute_query(q, {"repo": repository})

    # --- Phase 2: Chunk vector retrieval ---

    async def vector_search_chunks(
        self, k: int, vec: list[float], repository: str, limit: int
    ) -> QueryResultWrapper:
        """Semantic search over Chunk embeddings."""
        q = (
            "CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($vec)) "
            "YIELD node, score "
            "WHERE node.repository = $repository "
            "RETURN node.text AS text, node.file AS file, "
            "node.start_line AS start_line, node.end_line AS end_line, "
            "node.parent_uid AS parent_uid, node.parent_name AS parent_name, "
            "score "
            "ORDER BY score DESC LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"k": k, "vec": vec, "repository": repository, "limit": limit},
        )

    async def count_chunks_without_embedding(self, repository: str) -> QueryResultWrapper:
        """Count Chunk nodes that lack an embedding vector."""
        q = (
            "MATCH (c:Chunk {repository: $repo}) "
            "WHERE c.embedding IS NULL "
            "RETURN count(c) AS cnt"
        )
        return await self._store.execute_query(q, {"repo": repository})

    async def batch_get_chunks_for_embedding(
        self, repository: str, batch_size: int, offset: int
    ) -> QueryResultWrapper:
        """Fetch a batch of Chunk nodes without embeddings for indexing."""
        q = (
            "MATCH (c:Chunk {repository: $repo}) "
            "WHERE c.embedding IS NULL "
            "RETURN c.uid AS uid, c.text AS text "
            "ORDER BY c.uid "
            "SKIP $offset LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"repo": repository, "offset": offset, "limit": batch_size},
        )

    async def list_indexed_repositories(self) -> list[dict[str, Any]]:
        """List all repositories that have indexed modules."""
        q = (
            "MATCH (m:Module) WHERE m.repository IS NOT NULL "
            "RETURN m.repository AS repository, count(m) AS module_count "
            "ORDER BY module_count DESC"
        )
        result = await self._store.execute_query(q)
        rows = []
        for row in getattr(result, "raw", []) or []:
            rows.append({"repository": str(row[0]), "module_count": int(row[1])})
        return rows

    async def get_repo_wiki_freshness(
        self, business_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Per-repository freshness: latest indexed_at vs latest generated_at.

        Returns ``{repo_name: {"last_indexed": str|None, "last_generated": str|None}}``.
        Used by incremental business wiki generation to skip unchanged repos.
        """
        _ = business_id
        q = (
            "MATCH (m:Module) WHERE m.repository IS NOT NULL "
            "WITH m.repository AS repository, max(coalesce(m.indexed_at, '')) AS last_indexed "
            "OPTIONAL MATCH (wp:WikiPage {repository: repository}) "
            "WITH repository, last_indexed, max(coalesce(wp.generated_at, '')) AS last_generated "
            "RETURN repository, "
            "CASE WHEN last_indexed = '' THEN null ELSE last_indexed END AS last_indexed, "
            "CASE WHEN last_generated = '' THEN null ELSE last_generated END AS last_generated"
        )
        result = await self._store.execute_query(q)
        out: dict[str, dict[str, Any]] = {}
        for row in getattr(result, "data", []) or []:
            repo = str(row.get("repository", ""))
            if repo:
                out[repo] = {
                    "last_indexed": row.get("last_indexed"),
                    "last_generated": row.get("last_generated"),
                }
        return out

    async def get_suggested_questions_context(self, page_uid: str) -> dict[str, Any] | None:
        """Load wiki page and SOURCE_ENTITY graph (callers / callees) for question suggestions.

        Returns ``None`` if no :WikiPage exists for ``page_uid``. When no SOURCE_ENTITY is
        linked, returns a context using the page title and repository with empty graph lists.
        """
        q_wp = "MATCH (wp:WikiPage {uid: $uid}) RETURN wp AS wp LIMIT 1"
        r_wp = await self._store.execute_query(q_wp, {"uid": page_uid})
        if not r_wp.data:
            return None
        props = _wiki_node_properties(r_wp.data[0].get("wp"))
        title = str(props.get("title") or "")
        repo = str(props.get("repository") or "")

        _se = EdgeType.SOURCE_ENTITY.value
        q_ent = (
            f"MATCH (wp:WikiPage {{uid: $uid}})-[:{_se}]->(e) "
            "RETURN e.uid AS e_uid, coalesce(e.name, '') AS e_name, coalesce(e.repository, '') AS e_repo "
            "LIMIT 1"
        )
        r_ent = await self._store.execute_query(q_ent, {"uid": page_uid})
        if not r_ent.data or not r_ent.data[0].get("e_uid"):
            return {
                "page_uid": page_uid,
                "entity_name": title or "Unknown",
                "domain": repo,
                "callers": [],
                "callees": [],
                "cross_domain_callers": [],
            }
        row = r_ent.data[0]
        e_uid = str(row.get("e_uid") or "")
        e_name = str(row.get("e_name") or "") or title
        e_repo = str(row.get("e_repo") or "") or repo

        q_mod = (
            "MATCH (e) WHERE e.uid = $e_uid "
            "OPTIONAL MATCH (mod:Module)-[:CONTAINS|DECLARED_IN*0..3]-(e) "
            "RETURN coalesce(mod.name, mod.path, '') AS domain LIMIT 1"
        )
        r_mod = await self._store.execute_query(q_mod, {"e_uid": e_uid})
        domain = e_repo
        if r_mod.data:
            d = str(r_mod.data[0].get("domain") or "").strip()
            if d:
                domain = d

        q_call = (
            "MATCH (e) WHERE e.uid = $e_uid "
            "MATCH (caller)-[:CALLS]->(e) "
            "RETURN DISTINCT caller.name AS name, coalesce(caller.repository, '') AS repository"
        )
        r_call = await self._store.execute_query(q_call, {"e_uid": e_uid})
        callers: list[str] = []
        cross: list[str] = []
        for crow in r_call.data or []:
            nm = str(crow.get("name") or "").strip()
            if not nm:
                continue
            cr = str(crow.get("repository") or "").strip()
            if e_repo and cr and cr != e_repo:
                cross.append(nm)
            callers.append(nm)
        callers = list(dict.fromkeys(callers))
        cross = list(dict.fromkeys(cross))

        q_callee = (
            "MATCH (e) WHERE e.uid = $e_uid "
            "MATCH (e)-[:CALLS]->(callee) "
            "RETURN DISTINCT callee.name AS name"
        )
        r_cal = await self._store.execute_query(q_callee, {"e_uid": e_uid})
        callee_names = [
            str(x.get("name") or "").strip()
            for x in (r_cal.data or [])
            if x.get("name")
        ]
        callees = [n for n in dict.fromkeys(callee_names) if n]

        return {
            "page_uid": page_uid,
            "entity_name": e_name,
            "domain": domain,
            "callers": callers,
            "callees": callees,
            "cross_domain_callers": cross,
        }

    async def find_source_entity_mappings(
        self, repository: str | None = None
    ) -> list[dict[str, str]]:
        """WikiPage ↔ code entity rows for pages linked via SOURCE_ENTITY."""
        _se = EdgeType.SOURCE_ENTITY.value
        q = f"MATCH (wp:WikiPage)-[:{_se}]->(e) "
        params: dict[str, Any] = {}
        if repository is not None:
            q += "WHERE wp.repository = $repository "
            params["repository"] = repository
        q += (
            "RETURN wp.uid AS wiki_uid, e.uid AS entity_uid, "
            "coalesce(wp.path, '') AS path, coalesce(wp.repository, '') AS repository"
        )
        result = await self._store.execute_query(q, params or None)
        rows: list[dict[str, str]] = []
        for row in result.data:
            rows.append(
                {
                    "wiki_uid": str(row.get("wiki_uid") or ""),
                    "entity_uid": str(row.get("entity_uid") or ""),
                    "path": str(row.get("path") or ""),
                    "repository": str(row.get("repository") or ""),
                }
            )
        return rows

    async def find_code_entity_relationships(
        self, entity_uids: list[str] | None = None
    ) -> list[dict[str, str]]:
        """CALLS / INHERITS / IMPORTS / CROSS_REPO_CALLS between entities that have WikiPages."""
        _se = EdgeType.SOURCE_ENTITY.value
        rel_types = "|".join(
            (
                EdgeType.CALLS.value,
                EdgeType.INHERITS.value,
                EdgeType.IMPORTS.value,
                EdgeType.CROSS_REPO_CALLS.value,
            )
        )
        q = (
            f"MATCH (wp1:WikiPage)-[:{_se}]->(src) "
            f"MATCH (wp2:WikiPage)-[:{_se}]->(tgt) "
            f"MATCH (src)-[r:{rel_types}]->(tgt) "
        )
        params: dict[str, Any] = {}
        if entity_uids:
            q += "WHERE src.uid IN $entity_uids AND tgt.uid IN $entity_uids "
            params["entity_uids"] = entity_uids
        q += "RETURN src.uid AS source_uid, tgt.uid AS target_uid, type(r) AS rel_type"
        result = await self._store.execute_query(q, params or None)
        rows: list[dict[str, str]] = []
        for row in result.data:
            rows.append(
                {
                    "source_uid": str(row.get("source_uid") or ""),
                    "target_uid": str(row.get("target_uid") or ""),
                    "rel_type": str(row.get("rel_type") or ""),
                }
            )
        return rows

    async def assert_wiki_page_in_business(self, business_id: str, page_uid: str) -> bool:
        """Return whether ``page_uid`` is reachable from ``business_id`` via WikiSpace → HAS_CHILD → WikiPage."""
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage {uid: $page_uid}) "
            "RETURN 1 AS ok LIMIT 1"
        )
        r = await self.execute_query(q, {"business_id": business_id, "page_uid": page_uid})
        return bool(r.data)

    async def update_wiki_page_content(
        self,
        page_uid: str,
        content: str,
        source: str = "human_edit",
        expected_version: int | None = None,
        edit_reason: str = "",
    ) -> dict[str, Any]:
        """Update wiki page content, bump version, snapshot previous state on ``WikiPageVersion`` (LWW on mismatch)."""
        ex = await self.execute_query(
            "MATCH (wp:WikiPage {uid: $uid}) RETURN 1 AS ok LIMIT 1",
            {"uid": page_uid},
        )
        if not ex.data:
            return {"ok": False, "error": "wiki_page_not_found", "page_uid": page_uid}

        wv_uid = f"wpv:{page_uid}:{uuid.uuid4().hex[:16]}"
        created = datetime.now(timezone.utc).isoformat()
        cypher = (
            "MATCH (wp:WikiPage {uid: $page_uid}) "
            "WITH wp, coalesce(wp.version, 0) AS cur_v, coalesce(wp.content, '') AS old_c, "
            "coalesce(wp.content_source, '') AS old_src "
            "CREATE (wv:WikiPageVersion {"
            "uid: $wv_uid, wiki_page_uid: $page_uid, version: cur_v, content: old_c, "
            "edit_reason: $edit_reason, created_at: $created_at, content_source: old_src}) "
            "SET wp.content = $new_content, wp.content_source = $source, wp.version = cur_v + 1 "
            "RETURN cur_v + 1 AS new_version, cur_v AS previous_version, old_c AS old_content"
        )
        r = await self.execute_query(
            cypher,
            {
                "page_uid": page_uid,
                "new_content": content,
                "source": source,
                "edit_reason": edit_reason,
                "created_at": created,
                "wv_uid": wv_uid,
            },
        )
        if not r.data:
            return {"ok": False, "error": "wiki_page_update_failed", "page_uid": page_uid}
        row = r.data[0]
        new_v = int(row.get("new_version", 0))
        prev_v = int(row.get("previous_version", 0))
        mismatch = bool(
            expected_version is not None and int(expected_version) != prev_v
        )
        out: dict[str, Any] = {
            "ok": True,
            "page_uid": page_uid,
            "version": new_v,
            "previous_version": prev_v,
            "version_mismatch_warning": mismatch,
        }
        if mismatch:
            out["expected_version"] = expected_version
            out["server_version"] = prev_v
        return out

    async def _wiki_version_content(
        self, page_uid: str, version: int
    ) -> str | None:
        """Text at logical ``version``; ``None`` if page or version is unknown."""
        r_wp = await self.execute_query(
            "MATCH (wp:WikiPage {uid: $uid}) "
            "RETURN coalesce(wp.version, 0) AS v, coalesce(wp.content, '') AS c",
            {"uid": page_uid},
        )
        if not r_wp.data:
            return None
        cur = int(r_wp.data[0].get("v", 0) or 0)
        if version == cur:
            return str(r_wp.data[0].get("c") or "")
        wv = await self.execute_query(
            "MATCH (wv:WikiPageVersion {wiki_page_uid: $uid, version: $ver}) "
            "RETURN wv.content AS c LIMIT 1",
            {"uid": page_uid, "ver": version},
        )
        if wv.data:
            return str(wv.data[0].get("c") or "")
        return None

    def _hunks_from_unified(self, u_lines: list[str]) -> list[dict[str, Any]]:
        """Turn unified diff output into the dashboard ``WikiDiff`` hunk shape."""
        if not u_lines:
            return [
                {
                    "old_start": 1,
                    "old_lines": 0,
                    "new_start": 1,
                    "new_lines": 0,
                    "content": "",
                }
            ]
        return [
            {
                "old_start": 0,
                "old_lines": 0,
                "new_start": 0,
                "new_lines": 0,
                "content": "\n".join(u_lines),
            }
        ]

    async def get_wiki_page_version_diff(
        self,
        page_uid: str,
        from_version: int,
        to_version: int,
    ) -> dict[str, Any] | None:
        """Return ``WikiDiff``-shaped diff between two logical versions, or ``None`` if not found."""
        a = await self._wiki_version_content(page_uid, from_version)
        b = await self._wiki_version_content(page_uid, to_version)
        if a is None or b is None:
            return None
        a_lines = a.splitlines(keepends=True)
        b_lines = b.splitlines(keepends=True)
        u = list(
            difflib.unified_diff(
                a_lines,
                b_lines,
                fromfile=f"v{from_version}",
                tofile=f"v{to_version}",
                lineterm="",
            )
        )
        return {
            "from_version": from_version,
            "to_version": to_version,
            "hunks": self._hunks_from_unified(u),
        }

    async def list_wiki_page_versions(self, page_uid: str) -> list[dict[str, Any]]:
        """Rows compatible with the dashboard ``WikiVersion`` type (``version`` desc)."""
        r_wp = await self.execute_query(
            "MATCH (wp:WikiPage {uid: $uid}) "
            "RETURN coalesce(wp.version, 0) AS v, coalesce(wp.content, '') AS c, "
            "coalesce(wp.generated_at, '') AS generated_at, coalesce(wp.content_source, '') AS src",
            {"uid": page_uid},
        )
        if not r_wp.data:
            return []
        cur_v = int(r_wp.data[0].get("v", 0) or 0)
        body = r_wp.data[0]
        cur_content = str(body.get("c") or "")
        gen_at = str(body.get("generated_at") or "") or datetime.now(timezone.utc).isoformat()
        ch = hashlib.sha256(cur_content.encode("utf-8")).hexdigest()
        items: list[dict[str, Any]] = [
            {
                "version": cur_v,
                "content_hash": ch,
                "generated_at": gen_at,
                "change_summary": "",
            }
        ]
        wv = await self.execute_query(
            "MATCH (wv:WikiPageVersion {wiki_page_uid: $uid}) "
            "RETURN wv.version AS v, wv.content AS c, wv.created_at AS created_at, "
            "coalesce(wv.edit_reason, '') AS edit_reason, coalesce(wv.content_source, '') AS src",
            {"uid": page_uid},
        )
        for row in wv.data or []:
            vnum = int(row.get("v", 0) or 0)
            c = str(row.get("c") or "")
            h = hashlib.sha256(c.encode("utf-8")).hexdigest()
            items.append(
                {
                    "version": vnum,
                    "content_hash": h,
                    "generated_at": str(row.get("created_at") or gen_at),
                    "change_summary": str(row.get("edit_reason") or "history"),
                }
            )
        items.sort(key=lambda x: int(x.get("version", 0)), reverse=True)
        return items
