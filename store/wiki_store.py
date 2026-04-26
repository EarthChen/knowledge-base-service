"""Wiki-related Cypher queries (search, lint, fusion, routes, graph-enhanced ask)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from store.falkordb_store import QueryResultWrapper
from store.schema import EdgeType, NodeLabel


_SOURCE_DOC_EDGE = EdgeType.SOURCE_DOC.value


@runtime_checkable
class _GraphQueryPort(Protocol):
    """Any store or port that can run Cypher (FalkorDBStore, test doubles, etc.)."""

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any: ...


class WikiStore:
    """Wiki-related graph queries."""

    def __init__(self, base_store: _GraphQueryPort) -> None:
        self._store = base_store

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
            "WHERE wp.repository = $repository "
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
            "WHERE node.repository = $repository "
            "RETURN node, score LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"text": text, "repository": repository, "limit": limit},
        )

    async def vector_wiki_search(self, k: int, vec: list[float], repository: str, limit: int) -> QueryResultWrapper:
        q = (
            "CALL db.idx.vector.queryNodes('WikiPage', 'embedding', $k, vecf32($vec)) "
            "YIELD node, score "
            "WHERE node.repository = $repository "
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
            "RETURN wp.path AS path, wp.title AS title, wp.content AS content, "
            "coalesce(wp.generated_at, '') AS generated_at, "
            "coalesce(wp.referenced_entity_uids, []) AS referenced_entity_uids"
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
            f"MERGE (wp)-[:{_SOURCE_DOC_EDGE}]->(d) "
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
            "RETURN n.uid AS uid, labels(n)[0] AS label, "
            "coalesce(n.start_line, 0) AS start_line, "
            "coalesce(n.end_line, 0) AS end_line, "
            "count(DISTINCT in_e) AS in_degree, "
            "count(DISTINCT out_e) AS out_degree, "
            "count(DISTINCT child) AS children_count, "
            "count(DISTINCT sub) AS subclass_count"
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

    # --- Wiki tree structure CRUD ---

    _TREE_ALLOWED_LABELS = frozenset({"WikiSpace", "WikiSection", "WikiPage"})

    async def upsert_wiki_space(
        self, business_id: str, title: str, description: str
    ) -> QueryResultWrapper:
        uid = f"WikiSpace:{business_id}"
        q = (
            "MERGE (ws:WikiSpace {uid: $uid}) "
            "SET ws.business_id = $business_id, "
            "ws.title = $title, "
            "ws.description = $description, "
            "ws.updated_at = $ts "
            "ON CREATE SET ws.created_at = $ts "
            "RETURN ws.uid AS uid"
        )
        ts = datetime.now(timezone.utc).isoformat()
        return await self._store.execute_query(
            q, {"uid": uid, "business_id": business_id, "title": title,
                "description": description, "ts": ts},
        )

    async def upsert_wiki_section(
        self,
        uid: str,
        title: str,
        description: str,
        section_type: str,
        sort_order: int,
        icon: str | None = None,
        auto_generated: bool = True,
    ) -> QueryResultWrapper:
        q = (
            "MERGE (ws:WikiSection {uid: $uid}) "
            "SET ws.title = $title, "
            "ws.description = $description, "
            "ws.section_type = $section_type, "
            "ws.sort_order = $sort_order, "
            "ws.icon = $icon, "
            "ws.auto_generated = $auto_generated "
            "RETURN ws.uid AS uid"
        )
        return await self._store.execute_query(
            q, {"uid": uid, "title": title, "description": description,
                "section_type": section_type, "sort_order": sort_order,
                "icon": icon or "", "auto_generated": auto_generated},
        )

    async def add_has_child_edge(
        self,
        parent_uid: str,
        parent_label: str,
        child_uid: str,
        child_label: str,
        view_type: str,
        sort_order: int,
    ) -> QueryResultWrapper:
        if parent_label not in self._TREE_ALLOWED_LABELS:
            raise ValueError(f"Invalid parent_label '{parent_label}': must be one of {sorted(self._TREE_ALLOWED_LABELS)}")
        if child_label not in self._TREE_ALLOWED_LABELS:
            raise ValueError(f"Invalid child_label '{child_label}': must be one of {sorted(self._TREE_ALLOWED_LABELS)}")
        q = (
            f"MATCH (p:{parent_label} {{uid: $parent_uid}}) "
            f"MATCH (c:{child_label} {{uid: $child_uid}}) "
            "MERGE (p)-[r:HAS_CHILD {view_type: $view_type}]->(c) "
            "SET r.sort_order = $sort_order "
            "RETURN type(r) AS rel"
        )
        return await self._store.execute_query(
            q, {"parent_uid": parent_uid, "child_uid": child_uid,
                "view_type": view_type, "sort_order": sort_order},
        )

    async def add_wiki_reference_edge(
        self,
        source_uid: str,
        target_uid: str,
        relation_type: str,
        context: str = "",
        auto_generated: bool = True,
        confidence: float = 1.0,
    ) -> QueryResultWrapper:
        q = (
            "MATCH (s:WikiPage {uid: $source_uid}) "
            "MATCH (t:WikiPage {uid: $target_uid}) "
            "MERGE (s)-[r:WIKI_REFERENCES {relation_type: $relation_type}]->(t) "
            "SET r.context = $context, "
            "r.auto_generated = $auto_generated, "
            "r.confidence = $confidence "
            "RETURN type(r) AS rel"
        )
        return await self._store.execute_query(
            q, {"source_uid": source_uid, "target_uid": target_uid,
                "relation_type": relation_type, "context": context,
                "auto_generated": auto_generated, "confidence": confidence},
        )

    async def get_wiki_tree(
        self, business_id: str, view_type: str, max_depth: int = 5
    ) -> QueryResultWrapper:
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id}) "
            f"OPTIONAL MATCH path = (ws)-[:HAS_CHILD*1..{max_depth}]->(node) "
            "WHERE ALL(r IN relationships(path) WHERE r.view_type = $view_type) "
            "WITH node, length(path) AS depth "
            "WHERE node IS NOT NULL "
            "RETURN node.uid AS uid, node.title AS title, "
            "labels(node)[0] AS label, depth, "
            "node.sort_order AS sort_order, "
            "coalesce(node.path, '') AS path, "
            "coalesce(node.page_type, '') AS page_type "
            "ORDER BY depth, sort_order"
        )
        return await self._store.execute_query(
            q, {"business_id": business_id, "view_type": view_type},
        )

    async def get_wiki_page_references(self, page_uid: str) -> QueryResultWrapper:
        q = (
            "MATCH (s:WikiPage {uid: $uid})-[r:WIKI_REFERENCES]->(t:WikiPage) "
            "RETURN t.uid AS target_uid, t.title AS title, t.path AS path, "
            "t.repository AS repository, "
            "r.relation_type AS relation_type, r.context AS context "
            "ORDER BY r.relation_type, t.title"
        )
        return await self._store.execute_query(q, {"uid": page_uid})

    async def get_wiki_page_back_references(self, page_uid: str) -> QueryResultWrapper:
        q = (
            "MATCH (s:WikiPage)-[r:WIKI_REFERENCES]->(t:WikiPage {uid: $uid}) "
            "RETURN s.uid AS source_uid, s.title AS title, s.path AS path, "
            "s.repository AS repository, "
            "r.relation_type AS relation_type, r.context AS context "
            "ORDER BY r.relation_type, s.title"
        )
        return await self._store.execute_query(q, {"uid": page_uid})
