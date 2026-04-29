"""Wiki space / section / tree and cross-page link queries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from store.falkordb_store import QueryResultWrapper
class WikiTreeStoreMixin:
    """HAS_CHILD / WIKI_REFERENCES and business-scoped page listing."""

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
            "ws.updated_at = $ts, "
            "ws.created_at = coalesce(ws.created_at, $ts) "
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
        self,
        business_id: str,
        view_type: str,
        max_depth: int = 5,
        wiki_tier: str | None = None,
    ) -> QueryResultWrapper:
        tier_filter = ""
        if wiki_tier == "standard":
            tier_filter = (
                " AND (coalesce(labels(node)[0], '') <> 'WikiPage' OR "
                "coalesce(node.importance_tier, 'standard') NOT IN ['supplementary', 'skeleton'])"
            )
        elif wiki_tier == "essential":
            tier_filter = (
                " AND (coalesce(labels(node)[0], '') <> 'WikiPage' OR "
                "coalesce(node.importance_tier, 'standard') IN ['core', 'essential'])"
            )
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id}) "
            f"OPTIONAL MATCH path = (ws)-[:HAS_CHILD*1..{max_depth}]->(node) "
            "WHERE ALL(r IN relationships(path) WHERE r.view_type = $view_type) "
            "WITH ws, node, length(path) AS depth, "
            "CASE WHEN length(path) > 1 THEN nodes(path)[-2] ELSE ws END AS parent "
            f"WHERE node IS NOT NULL{tier_filter} "
            "RETURN node.uid AS uid, node.title AS title, "
            "labels(node)[0] AS label, depth, "
            "node.sort_order AS sort_order, "
            "coalesce(node.path, '') AS path, "
            "coalesce(node.page_type, '') AS page_type, "
            "parent.uid AS parent_uid "
            "ORDER BY depth, sort_order"
        )
        return await self._store.execute_query(
            q, {"business_id": business_id, "view_type": view_type},
        )

    async def get_nested_tree(
        self,
        root_uid: str,
        max_depth: int = 5,
        view_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Traverse nested :HAS_CHILD hierarchy from ``root_uid`` up to ``max_depth`` levels.

        Returns one row per reachable child (WikiSection or WikiPage) with graph distance
        ``depth`` from ``root``. When ``view_type`` is set, only paths whose every
        :HAS_CHILD relationship has that ``view_type`` are included (same semantics as
        ``get_wiki_tree``).
        """
        depth = max(1, min(int(max_depth), 50))
        if view_type is not None:
            q = (
                f"MATCH (root {{uid: $root_uid}})"
                f"MATCH path = (root)-[:HAS_CHILD*1..{depth}]->(child) "
                "WHERE ALL(r IN relationships(path) WHERE r.view_type = $view_type) "
                "RETURN child.uid AS uid, child.title AS title, length(path) AS depth "
                "ORDER BY depth, uid"
            )
            params: dict[str, Any] = {"root_uid": root_uid, "view_type": view_type}
        else:
            q = (
                f"MATCH path = (root {{uid: $root_uid}})"
                f"-[:HAS_CHILD*1..{depth}]->(child) "
                "RETURN child.uid AS uid, child.title AS title, length(path) AS depth "
                "ORDER BY depth, uid"
            )
            params = {"root_uid": root_uid}

        result = await self._store.execute_query(q, params)
        rows: list[dict[str, Any]] = []
        for row in result.data or []:
            rows.append({
                "uid": row.get("uid"),
                "title": row.get("title"),
                "depth": row.get("depth"),
            })
        return rows

    async def get_wiki_pages_for_business(
        self, business_id: str, min_tier: str = "skeleton"
    ) -> list[dict[str, Any]]:
        """Return all WikiPages under a business's WikiSpace tree."""
        tier_filter = ""
        if min_tier == "standard":
            tier_filter = "AND wp.importance_tier IN ['core', 'standard'] "
        elif min_tier == "core":
            tier_filter = "AND wp.importance_tier = 'core' "

        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id}) "
            "MATCH (ws)-[:HAS_CHILD*1..10]->(wp:WikiPage) "
            f"{tier_filter}"
            "OPTIONAL MATCH (wp)-[:SOURCE_ENTITY]->(e) "
            "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
            "wp.content AS content, wp.page_type AS page_type, "
            "wp.repository AS repository, wp.importance_tier AS importance_tier, "
            "coalesce(wp.content_hash, '') AS content_hash, "
            "coalesce(e.uid, '') AS entity_uid "
            "ORDER BY wp.path"
        )
        result = await self._store.execute_query(
            q, {"business_id": business_id}
        )
        rows: list[dict[str, Any]] = []
        for row in result.data:
            rows.append({
                "uid": str(row.get("uid") or ""),
                "title": str(row.get("title") or ""),
                "path": str(row.get("path") or ""),
                "content": str(row.get("content") or ""),
                "page_type": str(row.get("page_type") or ""),
                "repository": str(row.get("repository") or ""),
                "importance_tier": str(row.get("importance_tier") or ""),
                "content_hash": str(row.get("content_hash") or ""),
                "entity_uid": str(row.get("entity_uid") or ""),
            })
        return rows

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

    async def get_business_wiki_references_graph(self, business_id: str) -> dict[str, Any]:
        """All wiki pages under a business and cross-page :WIKI_REFERENCES with both ends in that tree."""
        q_pages = (
            "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
            "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
            "wp.repository AS repository, coalesce(wp.importance_tier, '') AS importance_tier "
            "ORDER BY wp.path"
        )
        pages = await self._store.execute_query(q_pages, {"business_id": business_id})
        q_edges = (
            "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(s:WikiPage) "
            "MATCH (s)-[r:WIKI_REFERENCES]->(t:WikiPage) "
            "MATCH (ws)-[:HAS_CHILD*1..10]->(t) "
            "RETURN s.uid AS source_uid, t.uid AS target_uid, r.relation_type AS relation_type"
        )
        edges = await self._store.execute_query(q_edges, {"business_id": business_id})
        return {
            "pages": list(pages.data) if pages and pages.data else [],
            "edges": list(edges.data) if edges and edges.data else [],
        }

    async def find_modules_by_domain(
        self, domain_name: str, business_id: str = "default"
    ) -> QueryResultWrapper:
        """Find modules matching a business domain, with optional wiki page paths."""
        q = (
            "MATCH (m:Module {business_domain: $domain}) "
            "OPTIONAL MATCH (wp:WikiPage)-[:SOURCE_ENTITY]->(m) "
            "RETURN m.uid AS uid, m.name AS name, m.path AS path, "
            "m.repository AS repository, wp.path AS wiki_page_path "
            "ORDER BY m.repository, m.path"
        )
        return await self._store.execute_query(q, {"domain": domain_name})
