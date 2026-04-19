"""Community detection on the code graph via label propagation (no extra deps)."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from store.falkordb_store import FalkorDBStore


def _majority_label(neighbor_labels: list[int]) -> int:
    if not neighbor_labels:
        return -1
    ctr = Counter(neighbor_labels)
    best = max(ctr.values())
    candidates = [k for k, v in ctr.items() if v == best]
    return min(candidates)


class CommunityDetector:
    """Detect code communities using label propagation on the code graph."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def detect(
        self,
        *,
        repository: str | None = None,
        min_community_size: int = 3,
    ) -> dict[str, Any]:
        """Detect communities in the code graph."""
        min_sz = max(2, min(int(min_community_size), 500))

        nodes_q = """
            MATCH (n)
            WHERE (n:Function OR n:Class)
            AND ($repository IS NULL OR n.repository = $repository)
            /* community_nodes */
            RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS typ,
            coalesce(n.file, '') AS file
        """
        edges_q = """
            MATCH (a)-[r:CALLS|INHERITS|IMPORTS]->(b)
            WHERE (a:Function OR a:Class) AND (b:Function OR b:Class)
            AND ($repository IS NULL OR (a.repository = $repository AND b.repository = $repository))
            /* community_edges */
            RETURN a.uid AS src, b.uid AS tgt
        """

        params = {"repository": repository}
        nrows = (await self._store.execute_query(nodes_q, params)).data
        erows = (await self._store.execute_query(edges_q, params)).data

        if not nrows:
            return {
                "communities": [],
                "total_communities": 0,
                "unclustered_count": 0,
            }

        uids = [str(r["uid"]) for r in nrows if r.get("uid")]
        uid_set = set(uids)
        idx: dict[str, int] = {u: i for i, u in enumerate(uids)}
        meta = {str(r["uid"]): r for r in nrows if r.get("uid")}

        adj: list[set[int]] = [set() for _ in uids]
        edge_pairs: set[tuple[str, str]] = set()

        for row in erows:
            su = str(row.get("src") or "")
            tu = str(row.get("tgt") or "")
            if su not in uid_set or tu not in uid_set:
                continue
            i, j = idx[su], idx[tu]
            adj[i].add(j)
            adj[j].add(i)
            a, b = (su, tu) if su <= tu else (tu, su)
            edge_pairs.add((a, b))

        n = len(uids)
        labels = list(range(n))
        order = sorted(range(n), key=lambda i: uids[i])

        max_iter = min(100, max(30, n * 3))
        for _ in range(max_iter):
            new_labels = labels[:]
            for i in order:
                neigh_idx = adj[i]
                if not neigh_idx:
                    continue
                neigh_lbl = [labels[j] for j in sorted(neigh_idx)]
                ml = _majority_label(neigh_lbl)
                if ml >= 0:
                    new_labels[i] = ml
            if new_labels == labels:
                break
            labels = new_labels

        buckets: dict[int, list[int]] = defaultdict(list)
        for i, lb in enumerate(labels):
            buckets[lb].append(i)

        degree: list[int] = [len(adj[i]) for i in range(n)]

        large: list[tuple[int, list[int]]] = []
        unclustered = 0
        for lb, members in buckets.items():
            if len(members) >= min_sz:
                large.append((lb, members))
            else:
                unclustered += len(members)

        large.sort(key=lambda x: len(x[1]), reverse=True)

        communities_out: list[dict[str, Any]] = []
        for new_id, (_old_lb, memb_idx) in enumerate(large):
            memb_uids = [uids[i] for i in memb_idx]
            memb_set = set(memb_uids)
            top_names = sorted(
                memb_idx,
                key=lambda i: (-degree[i], uids[i]),
            )[:3]
            label_parts = []
            for i in top_names:
                name = str(meta.get(uids[i], {}).get("name") or "").strip()
                if name:
                    label_parts.append(name)
            label_str = " / ".join(label_parts) if label_parts else " / ".join(memb_uids[:3])

            internal = 0
            for a, b in edge_pairs:
                if a in memb_set and b in memb_set:
                    internal += 1
            m = len(memb_uids)
            possible = m * (m - 1) / 2 if m >= 2 else 0.0
            cohesion = round(internal / possible, 4) if possible > 0 else 0.0

            member_rows: list[dict[str, Any]] = []
            for i in sorted(memb_idx, key=lambda x: uids[x]):
                u = uids[i]
                row = meta.get(u, {})
                member_rows.append({
                    "uid": u,
                    "name": str(row.get("name") or ""),
                    "type": str(row.get("typ") or ""),
                    "file": str(row.get("file") or ""),
                })

            communities_out.append({
                "id": new_id,
                "label": label_str,
                "size": m,
                "members": member_rows,
                "cohesion": cohesion,
            })

        return {
            "communities": communities_out,
            "total_communities": len(communities_out),
            "unclustered_count": unclustered,
        }
