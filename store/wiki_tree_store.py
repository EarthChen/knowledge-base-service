"""Wiki space / section / tree and cross-page link queries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

_TOPIC_PAGE_TYPES = frozenset({"topic", "domain_overview"})

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

    async def persist_pipeline_domain_tree(
        self, business_id: str, domain_tree: list[Any], review_status: dict[str, Any] | None = None,
    ) -> None:
        """Persist the pipeline domain tree and review status as JSON blobs on WikiSpace."""
        uid = f"WikiSpace:{business_id}"
        tree_json = json.dumps(domain_tree, ensure_ascii=False)
        status_json = json.dumps(review_status or {}, ensure_ascii=False)
        q = (
            "MATCH (ws:WikiSpace {uid: $uid}) "
            "SET ws.pipeline_domain_tree = $tree_json, "
            "ws.pipeline_review_status = $status_json "
            "RETURN ws.uid AS uid"
        )
        await self._store.execute_query(
            q, {"uid": uid, "tree_json": tree_json, "status_json": status_json},
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

    async def remove_has_child_edge(
        self, parent_uid: str, child_uid: str, view_type: str,
    ) -> bool:
        q = (
            "MATCH (p)-[r:HAS_CHILD {view_type: $vt}]->(c) "
            "WHERE p.uid = $parent AND c.uid = $child "
            "DELETE r "
            "RETURN count(r) AS deleted"
        )
        result = await self._store.execute_query(q, {
            "parent": parent_uid, "child": child_uid, "vt": view_type,
        })
        rows = getattr(result, "data", None) or []
        return bool(rows and rows[0].get("deleted", 0) > 0)

    async def reparent_children(
        self, old_parent_uid: str, new_parent_uid: str, view_type: str,
    ) -> int:
        q = (
            "MATCH (old {uid: $old_parent})-[r:HAS_CHILD {view_type: $vt}]->(child) "
            "WITH old, r, child, r.sort_order AS so "
            "DELETE r "
            "WITH child, so "
            "MATCH (new_p {uid: $new_parent}) "
            "CREATE (new_p)-[:HAS_CHILD {view_type: $vt, sort_order: so}]->(child) "
            "RETURN count(child) AS moved"
        )
        result = await self._store.execute_query(q, {
            "old_parent": old_parent_uid,
            "new_parent": new_parent_uid,
            "vt": view_type,
        })
        rows = getattr(result, "data", None) or []
        return int(rows[0].get("moved", 0)) if rows else 0

    async def delete_wiki_section_cascade(
        self, uid: str, view_type: str = "business_domain",
    ) -> int:
        q = (
            "MATCH (s {uid: $uid})-[:HAS_CHILD*0.. {view_type: $vt}]->(d) "
            "DETACH DELETE d "
            "RETURN count(d) AS deleted"
        )
        result = await self._store.execute_query(
            q, {"uid": uid, "vt": view_type},
        )
        rows = getattr(result, "data", None) or []
        return int(rows[0].get("deleted", 0)) if rows else 0

    async def get_section_parent(
        self, section_uid: str, view_type: str,
    ) -> str | None:
        q = (
            "MATCH (p)-[:HAS_CHILD {view_type: $vt}]->(s {uid: $uid}) "
            "RETURN p.uid AS uid LIMIT 1"
        )
        result = await self._store.execute_query(q, {"uid": section_uid, "vt": view_type})
        rows = getattr(result, "data", None) or []
        return str(rows[0]["uid"]) if rows else None

    async def get_section_children(
        self, section_uid: str, view_type: str,
    ) -> list[dict[str, Any]]:
        q = (
            "MATCH (s {uid: $uid})-[r:HAS_CHILD {view_type: $vt}]->(child) "
            "RETURN child.uid AS uid, child.title AS title, labels(child) AS labels "
            "ORDER BY r.sort_order"
        )
        result = await self._store.execute_query(q, {"uid": section_uid, "vt": view_type})
        rows = getattr(result, "data", None) or []
        return [
            {"uid": str(r.get("uid", "")), "title": str(r.get("title", "")), "labels": r.get("labels", [])}
            for r in rows if r.get("uid")
        ]

    async def get_section_descendants(
        self, section_uid: str, view_type: str,
    ) -> list[str]:
        q = (
            "MATCH (s {uid: $uid})-[:HAS_CHILD*1.. {view_type: $vt}]->(d) "
            "RETURN DISTINCT d.uid AS uid"
        )
        result = await self._store.execute_query(q, {"uid": section_uid, "vt": view_type})
        rows = getattr(result, "data", None) or []
        return [str(r["uid"]) for r in rows if r.get("uid")]

    _SECTION_WRITABLE_PROPS = frozenset({
        "title", "description", "user_modified", "sort_order", "icon",
    })

    async def update_section_properties(
        self, uid: str, properties: dict[str, Any],
    ) -> bool:
        set_clauses = []
        params: dict[str, Any] = {"uid": uid}
        for key, value in properties.items():
            if key not in self._SECTION_WRITABLE_PROPS:
                raise ValueError(f"Property '{key}' is not writable on WikiSection")
            param_name = f"p_{key}"
            set_clauses.append(f"s.{key} = ${param_name}")
            params[param_name] = value
        if not set_clauses:
            return False
        q = f"MATCH (s:WikiSection {{uid: $uid}}) SET {', '.join(set_clauses)} RETURN 1 AS updated"
        result = await self._store.execute_query(q, params)
        rows = getattr(result, "data", None) or []
        return bool(rows)

    async def update_module_business_domain(
        self, module_uid: str, domain: str,
    ) -> bool:
        q = (
            "MATCH (m:Module {uid: $uid}) "
            "SET m.business_domain = $domain "
            "RETURN 1 AS updated"
        )
        result = await self._store.execute_query(q, {"uid": module_uid, "domain": domain})
        rows = getattr(result, "data", None) or []
        return bool(rows)

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

    def _nested_trees_from_wiki_tree_rows(
        self, flat_rows: list[list[Any]],
    ) -> list[dict[str, Any]]:
        """Turn positional rows from ``get_wiki_tree`` into nested dicts with ``children``."""
        flat_nodes: list[dict[str, Any]] = []
        for row in flat_rows:
            flat_nodes.append(
                {
                    "uid": row[0],
                    "title": str(row[1] or ""),
                    "label": str(row[2] or ""),
                    "depth": row[3],
                    "sort_order": row[4],
                    "path": str(row[5] or ""),
                    "page_type": str(row[6] or ""),
                    "children": [],
                    "_parent_uid": row[7] if len(row) > 7 else None,
                }
            )
        node_map: dict[str, dict[str, Any]] = {str(n["uid"]): n for n in flat_nodes if n.get("uid")}
        roots: list[dict[str, Any]] = []
        for n in flat_nodes:
            parent_uid = n.pop("_parent_uid", None)
            puid = str(parent_uid) if parent_uid is not None else ""
            if puid and puid in node_map:
                node_map[puid]["children"].append(n)
            else:
                roots.append(n)
        return roots

    def _prune_wiki_tree_to_topic_pages(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep ``WikiPage`` nodes whose ``page_type`` is topic or domain_overview.

        Also keep ``WikiSection`` nodes unconditionally (they represent
        curated domain/topic categories and should be visible even before
        wiki pages are generated underneath them).
        """

        def visit(n: dict[str, Any]) -> dict[str, Any] | None:
            label = str(n.get("label") or "")
            pt = str(n.get("page_type") or "").strip().lower()
            pruned_children: list[dict[str, Any]] = []
            for ch in n.get("children") or []:
                pc = visit(ch)
                if pc is not None:
                    pruned_children.append(pc)
            if label == "WikiPage":
                if pt in _TOPIC_PAGE_TYPES:
                    out = {k: v for k, v in n.items() if k != "children"}
                    out["children"] = pruned_children
                    out.setdefault("name", str(out.get("title") or ""))
                    return out
                return None
            # WikiSection: always keep (domain sections should be visible
            # immediately after domain classification, even without pages yet)
            out = {k: v for k, v in n.items() if k != "children"}
            out["children"] = pruned_children
            out.setdefault("name", str(out.get("title") or ""))
            return out

        result: list[dict[str, Any]] = []
        for n in nodes:
            pr = visit(n)
            if pr is not None:
                # Flatten __root__ wrapper: promote its children to top level
                title = str(pr.get("title") or "")
                if title == "__root__" and pr.get("children"):
                    result.extend(pr["children"])
                else:
                    result.append(pr)
        return result

    async def get_pipeline_domain_tree_snapshot(self, business_id: str) -> dict[str, Any]:
        """Load pipeline domain tree + review status persisted on ``WikiSpace`` (JSON blobs).

        Properties (optional): ``pipeline_domain_tree``, ``pipeline_review_status``.
        """
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id}) "
            "RETURN coalesce(ws.pipeline_domain_tree, '') AS tree_raw, "
            "coalesce(ws.pipeline_review_status, '') AS status_raw "
            "LIMIT 1"
        )
        result = await self._store.execute_query(q, {"business_id": business_id})
        rows = getattr(result, "data", None) or []
        tree: list[Any] = []
        review_status: dict[str, Any] = {}
        if rows and isinstance(rows[0], dict):
            tr = str(rows[0].get("tree_raw") or "").strip()
            sr = str(rows[0].get("status_raw") or "").strip()
            if tr:
                try:
                    parsed = json.loads(tr)
                    if isinstance(parsed, list):
                        tree = parsed
                except json.JSONDecodeError:
                    pass
            if sr:
                try:
                    parsed = json.loads(sr)
                    if isinstance(parsed, dict):
                        review_status = parsed
                except json.JSONDecodeError:
                    pass
        return {"tree": tree, "review_status": review_status}

    async def get_topic_navigation_tree(self, business_id: str) -> list[dict[str, Any]]:
        """Business-domain wiki tree filtered to topic and domain_overview pages (dashboard navigation)."""
        result = await self.get_wiki_tree(business_id, "business_domain", wiki_tier=None)
        flat = list(result.result_set or []) if result else []
        roots = self._nested_trees_from_wiki_tree_rows(flat)
        return self._prune_wiki_tree_to_topic_pages(roots)

    async def get_domain_edges(self, business_id: str) -> dict[str, Any]:
        """Compute cross-domain relationship edges.

        Finds CALLS edges between entities whose wiki pages sit under different
        top-level WikiSection buckets in the business_domain view (first section
        on the path from WikiSpace to the page).
        """
        q = (
            "MATCH (ws:WikiSpace {business_id: $bid}) "
            "MATCH pth1 = (ws)-[:HAS_CHILD*1..10]->(wp1:WikiPage) "
            "WHERE ALL(r IN relationships(pth1) WHERE r.view_type = 'business_domain') "
            "MATCH (wp1)-[:SOURCE_ENTITY]->(e1)-[:CALLS]->(e2)<-[:SOURCE_ENTITY]-(wp2:WikiPage) "
            "MATCH pth2 = (ws)-[:HAS_CHILD*1..10]->(wp2) "
            "WHERE ALL(r IN relationships(pth2) WHERE r.view_type = 'business_domain') "
            "WITH "
            "head([n IN tail(nodes(pth1)) WHERE 'WikiSection' IN labels(n) | coalesce(n.title, '')]) AS domain1, "
            "head([n IN tail(nodes(pth2)) WHERE 'WikiSection' IN labels(n) | coalesce(n.title, '')]) AS domain2 "
            "WHERE domain1 <> '' AND domain2 <> '' AND domain1 <> domain2 "
            "RETURN domain1 AS source, domain2 AS target, count(*) AS weight "
            "ORDER BY weight DESC "
            "LIMIT 50"
        )
        try:
            result = await self._store.execute_query(q, {"bid": business_id})
            rows = list(getattr(result, "data", None) or [])
            edges: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for row in rows:
                src = row.get("source") if isinstance(row, dict) else None
                tgt = row.get("target") if isinstance(row, dict) else None
                weight = row.get("weight") if isinstance(row, dict) else None
                if not isinstance(src, str) or not isinstance(tgt, str):
                    continue
                key = (src, tgt)
                if key not in seen and (tgt, src) not in seen:
                    seen.add(key)
                    w = int(weight) if weight is not None else 0
                    edges.append({
                        "source": src,
                        "target": tgt,
                        "label": f"CALLS ({w})",
                    })
            return {"edges": edges}
        except Exception:
            return {"edges": []}

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

    async def get_wiki_page_references_batch(
        self, page_uids: list[str], *, chunk_size: int = 500,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return outgoing WIKI_REFERENCES for many pages in one or few UNWIND queries."""
        if not page_uids:
            return {}
        q = (
            "UNWIND $uids AS uid "
            "MATCH (s:WikiPage {uid: uid})-[r:WIKI_REFERENCES]->(t:WikiPage) "
            "RETURN uid AS source_uid, t.path AS path, t.title AS title, "
            "t.repository AS repository, "
            "r.relation_type AS relation_type, r.context AS context "
            "ORDER BY uid, r.relation_type, t.title"
        )
        out: dict[str, list[dict[str, Any]]] = {uid: [] for uid in page_uids}
        for i in range(0, len(page_uids), chunk_size):
            batch = page_uids[i : i + chunk_size]
            result = await self._store.execute_query(q, {"uids": batch})
            for row in result.data or []:
                if not isinstance(row, dict):
                    continue
                src = str(row.get("source_uid") or "")
                if src in out:
                    out[src].append(row)
        return out

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
        """Find modules matching a business domain, with optional wiki page paths.

        Uses COLLECT to deduplicate when multiple WikiPages reference the same Module.
        """
        q = (
            "MATCH (m:Module {business_domain: $domain}) "
            "OPTIONAL MATCH (wp:WikiPage)-[:SOURCE_ENTITY]->(m) "
            "WITH m, COLLECT(DISTINCT wp.path) AS wiki_paths "
            "RETURN m.uid AS uid, m.name AS name, m.path AS path, "
            "m.repository AS repository, wiki_paths[0] AS wiki_page_path "
            "ORDER BY m.repository, m.path"
        )
        return await self._store.execute_query(q, {"domain": domain_name})
