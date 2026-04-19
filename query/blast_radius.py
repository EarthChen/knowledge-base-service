"""Blast-radius (upstream impact) analysis for code graph entities."""

from __future__ import annotations

from collections import Counter
from collections import deque
from typing import Any

from query.graph_query import _make_params
from store.falkordb_store import FalkorDBStore


def _confidence_for_depth(depth: int) -> float:
    """Higher confidence closer to the change; decays by hop depth."""
    if depth <= 0:
        return 1.0
    base = 1.0 / (1.0 + 0.35 * float(depth - 1))
    return round(max(0.05, min(1.0, base)), 4)


class BlastRadiusAnalyzer:
    """Analyze the impact radius of code changes."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def analyze(
        self,
        entity_names: list[str],
        *,
        max_depth: int = 3,
        repository: str | None = None,
    ) -> dict[str, Any]:
        """Compute blast radius for given entity changes."""
        md = max(1, min(int(max_depth), 50))
        names = [str(n).strip() for n in entity_names if str(n).strip()]
        if not names:
            return self._empty_result([], md)

        center_entities: list[dict[str, Any]] = []
        seen_uid: set[str] = set()
        for raw in names:
            rows = await self._resolve_entity(raw, repository)
            for row in rows:
                uid = str(row.get("uid") or "")
                if not uid or uid in seen_uid:
                    continue
                seen_uid.add(uid)
                center_entities.append(self._format_center(row))

        center_uids = {e["uid"] for e in center_entities}
        if not center_uids:
            return self._empty_result([], md)

        # BFS: (entity_uid, depth) — expand incoming impact edges (caller / importer / subclass).
        visited_depth: dict[str, int] = {}
        relation_from_parent: dict[str, str] = {}
        queue: deque[tuple[str, int]] = deque()

        for uid in center_uids:
            visited_depth[uid] = 0
            queue.append((uid, 0))

        while queue:
            entity_uid, d = queue.popleft()
            if d >= md:
                continue
            frontier = await self._incoming_neighbors([entity_uid], repository)
            for row in frontier:
                n_uid = str(row.get("uid") or "")
                if not n_uid or n_uid in center_uids:
                    continue
                rel = str(row.get("relation") or "RELATED")
                nd = d + 1
                prev = visited_depth.get(n_uid)
                if prev is None or nd < prev:
                    visited_depth[n_uid] = nd
                    relation_from_parent[n_uid] = rel
                    queue.append((n_uid, nd))

        # Build layers (exclude centers from affected).
        layers_map: dict[int, list[dict[str, Any]]] = {}
        max_layer = 0
        for uid, dep in visited_depth.items():
            if uid in center_uids or dep < 1:
                continue
            layers_map.setdefault(dep, []).append(uid)
            max_layer = max(max_layer, dep)

        affected_layers: list[dict[str, Any]] = []
        detail_cache: dict[str, dict[str, Any]] = {}

        for depth in sorted(layers_map.keys()):
            uids = layers_map[depth]
            detail_cache.update(await self._hydrate_nodes(uids, repository))
            nodes_out: list[dict[str, Any]] = []
            by_type: Counter[str] = Counter()
            by_rel: Counter[str] = Counter()
            for uid in sorted(uids):
                meta = detail_cache.get(uid, {})
                rel = relation_from_parent.get(uid, "RELATED")
                typ = str(meta.get("type") or "Unknown")
                by_type[typ] += 1
                by_rel[rel] += 1
                nodes_out.append({
                    "uid": uid,
                    "name": meta.get("name", ""),
                    "type": typ,
                    "file": meta.get("file", ""),
                    "relation": rel,
                    "confidence": _confidence_for_depth(depth),
                })
            affected_layers.append({"depth": depth, "nodes": nodes_out})

        total_affected = sum(len(x["nodes"]) for x in affected_layers)

        agg_type: Counter[str] = Counter()
        agg_rel: Counter[str] = Counter()
        for layer in affected_layers:
            for n in layer["nodes"]:
                agg_type[str(n.get("type") or "")] += 1
                agg_rel[str(n.get("relation") or "")] += 1

        return {
            "center_entities": center_entities,
            "affected": affected_layers,
            "total_affected": total_affected,
            "summary": {
                "by_type": dict(sorted(agg_type.items())),
                "by_relation": dict(sorted(agg_rel.items())),
                "max_depth_reached": max_layer,
            },
        }

    def _empty_result(self, centers: list[dict[str, Any]], md: int) -> dict[str, Any]:
        return {
            "center_entities": centers,
            "affected": [],
            "total_affected": 0,
            "summary": {
                "by_type": {},
                "by_relation": {},
                "max_depth_reached": 0,
            },
        }

    async def _resolve_entity(self, raw_name: str, repository: str | None) -> list[dict[str, Any]]:
        params = {**_make_params(raw_name), "repository": repository}
        query = (
            "MATCH (n) WHERE (n:Function OR n:Class OR n:Module) "
            "AND (n.fqn = $fqn OR n.name = $simple_name) "
            "AND ($repository IS NULL OR n.repository = $repository) "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS typ, "
            "coalesce(n.file, '') AS file, coalesce(n.start_line, 0) AS line"
        )
        result = await self._store.execute_query(query, params)
        return result.data

    async def _incoming_neighbors(
        self,
        uids: list[str],
        repository: str | None,
    ) -> list[dict[str, Any]]:
        if not uids:
            return []
        query = (
            "UNWIND $uids AS uid "
            "MATCH (entity {uid: uid}) "
            "MATCH (nbr)-[r:CALLS|IMPORTS|INHERITS]->(entity) "
            "WHERE ($repository IS NULL OR (entity.repository = $repository AND nbr.repository = $repository)) "
            "RETURN DISTINCT nbr.uid AS uid, nbr.name AS name, labels(nbr)[0] AS typ, "
            "coalesce(nbr.file, '') AS file, coalesce(nbr.start_line, 0) AS line, type(r) AS relation"
        )
        result = await self._store.execute_query(
            query,
            {"uids": uids, "repository": repository},
        )
        return result.data

    async def _hydrate_nodes(self, uids: list[str], repository: str | None) -> dict[str, dict[str, Any]]:
        if not uids:
            return {}
        query = (
            "UNWIND $uids AS uid "
            "MATCH (n {uid: uid}) "
            "WHERE $repository IS NULL OR n.repository = $repository "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS typ, "
            "coalesce(n.file, '') AS file, coalesce(n.start_line, 0) AS line"
        )
        result = await self._store.execute_query(query, {"uids": uids, "repository": repository})
        out: dict[str, dict[str, Any]] = {}
        for row in result.data:
            uid = str(row.get("uid") or "")
            if uid:
                out[uid] = {
                    "name": row.get("name", ""),
                    "type": str(row.get("typ") or ""),
                    "file": row.get("file", ""),
                    "line": row.get("line"),
                }
        # Fallback for uids missing from hydrate (repository drift): minimal dict.
        for u in uids:
            if u not in out:
                out[u] = {"name": "", "type": "", "file": "", "line": None}
        return out

    def _format_center(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "uid": str(row.get("uid") or ""),
            "name": str(row.get("name") or ""),
            "type": str(row.get("typ") or ""),
            "file": str(row.get("file") or ""),
            "line": row.get("line"),
        }
