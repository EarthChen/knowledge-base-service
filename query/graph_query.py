"""Graph query interface — parameterized Cypher templates for code analysis.

Provides pre-built Cypher query templates for common code analysis tasks:
call chains, inheritance trees, module dependencies, and entity lookups.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from store.falkordb_store import FalkorDBStore
from store.traversal_store import TraversalStore, make_name_query_params

# Backward compatibility for callers importing name-resolution helpers from this module.
_make_params = make_name_query_params


@dataclass
class QueryResult:
    data: list[dict[str, Any]]
    query: str
    params: dict[str, Any]


class GraphQueryService:
    """Provides parameterized Cypher graph queries over the code knowledge graph."""

    def __init__(
        self,
        store: FalkorDBStore,
        traversal: TraversalStore | None = None,
    ) -> None:
        self._store = store
        self._traversal = traversal or TraversalStore(store)

    async def find_call_chain(
        self, function_name: str, depth: int = 3, direction: str = "downstream",
    ) -> QueryResult:
        """Find the call chain starting from a function.

        Accepts simple name (``loginV2``) or FQN (``com.foo.Bar#loginV2``).
        Returns nodes and edges for multi-level visualization.
        """
        run = await self._traversal.find_call_chain(function_name, depth, direction)
        rows = run.rows
        query = run.query
        params = run.params

        nodes_map: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []

        for r in rows.data:
            src_key = f"{r.get('src_name', '')}:{r.get('src_line', 0)}"
            tgt_key = f"{r.get('tgt_name', '')}:{r.get('tgt_line', 0)}"
            if src_key not in nodes_map:
                src_sl = r.get("src_line", 0)
                src_el = r.get("src_end_line")
                if src_el is None:
                    src_el = src_sl
                nodes_map[src_key] = {
                    "name": r.get("src_name", ""),
                    "file": r.get("src_file", ""),
                    "line": src_sl,
                    "start_line": src_sl,
                    "end_line": src_el,
                    "fqn": r.get("src_fqn", ""),
                }
            if tgt_key not in nodes_map:
                tgt_sl = r.get("tgt_line", 0)
                tgt_el = r.get("tgt_end_line")
                if tgt_el is None:
                    tgt_el = tgt_sl
                nodes_map[tgt_key] = {
                    "name": r.get("tgt_name", ""),
                    "file": r.get("tgt_file", ""),
                    "line": tgt_sl,
                    "start_line": tgt_sl,
                    "end_line": tgt_el,
                    "fqn": r.get("tgt_fqn", ""),
                }
            edges.append({"source": src_key, "target": tgt_key})

        data = list(nodes_map.values())
        return QueryResult(
            data=data,
            query=query,
            params={**params, "_edges": edges},
        )

    async def find_inheritance_tree(self, class_name: str, direction: str = "children") -> QueryResult:
        """Find inheritance hierarchy for a class.

        Accepts simple name or FQN.
        """
        run = await self._traversal.find_inheritance_tree(class_name, direction)
        rows = run.rows
        query = run.query
        params = run.params
        data: list[dict[str, Any]] = []
        for r in rows.data:
            sl = r.get("start_line", 0)
            el = r.get("end_line")
            if el is None:
                el = sl
            data.append({
                "name": r.get("name", ""),
                "file": r.get("file", ""),
                "line": sl,
                "start_line": sl,
                "end_line": el,
            })
        return QueryResult(data=data, query=query, params=params)

    async def find_class_methods(self, class_name: str) -> QueryResult:
        """Find all methods belonging to a class. Accepts simple name or FQN."""
        run = await self._traversal.find_class_methods(class_name)
        rows = run.rows
        query = run.query
        params = run.params
        data = []
        for r in rows.data:
            sl = r.get("start_line", 0)
            el = r.get("end_line")
            if el is None:
                el = sl
            data.append({
                "name": r.get("name", ""),
                "signature": r.get("signature", ""),
                "file": r.get("file", ""),
                "line": sl,
                "start_line": sl,
                "end_line": el,
            })
        return QueryResult(data=data, query=query, params=params)

    async def find_module_dependencies(self, module_name: str) -> QueryResult:
        """Find what a module imports."""
        run = await self._traversal.find_module_dependencies(module_name)
        rows = run.rows
        query = run.query
        params = run.params
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_reverse_dependencies(self, module_name: str) -> QueryResult:
        """Find what modules import this module."""
        run = await self._traversal.find_reverse_dependencies(module_name)
        rows = run.rows
        query = run.query
        params = run.params
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_entity(self, name: str, entity_type: str = "any") -> QueryResult:
        """Find a code entity by name or FQN."""
        run = await self._traversal.find_entity(name, entity_type)
        rows = run.rows
        query = run.query
        params = run.params
        data = [
            {"name": r[0], "file": r[1], "line": r[2], "signature": r[3], "docstring": r[4], "type": r[5]}
            for r in rows
        ]
        return QueryResult(data=data, query=query, params=params)

    async def find_file_entities(self, file_path: str) -> QueryResult:
        """Find all entities defined in a file."""
        run = await self._traversal.find_file_entities(file_path)
        rows = run.rows
        query = run.query
        params = run.params
        data = [
            {
                "name": r[0],
                "type": r[1],
                "line": r[2],
                "end_line": r[3],
                "signature": r[4],
                "uid": r[5],
                "docstring": r[6],
            }
            for r in rows
        ]
        return QueryResult(data=data, query=query, params=params)

    async def execute_raw(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Execute a read-only raw Cypher query with mandatory LIMIT and timeout."""
        import asyncio

        from query.raw_cypher import (
            RAW_CYPHER_TIMEOUT_SEC,
            ensure_raw_cypher_limit,
            validate_raw_cypher_read_only,
        )

        validate_raw_cypher_read_only(cypher)
        safe_cypher = ensure_raw_cypher_limit(cypher)
        try:
            rows = await asyncio.wait_for(
                self._store.execute_query(safe_cypher, params),
                timeout=RAW_CYPHER_TIMEOUT_SEC,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"raw_cypher query exceeded {RAW_CYPHER_TIMEOUT_SEC:.0f}s timeout"
            ) from exc
        data = [{"row": list(r)} for r in rows]
        return QueryResult(data=data, query=safe_cypher, params=params or {})

    async def get_graph_stats(self) -> dict[str, int]:
        """Get statistics about the knowledge graph."""
        import asyncio

        labels = ("Function", "Class", "Module", "Document")
        edge_types = ("CALLS", "INHERITS", "IMPORTS", "CONTAINS", "REFERENCES")
        label_tasks = [self._traversal.count_nodes_by_label(lbl) for lbl in labels]
        edge_tasks = [self._traversal.count_edges_by_type(et) for et in edge_types]
        results = await asyncio.gather(*label_tasks, *edge_tasks)

        stats: dict[str, int] = {}
        for i, label in enumerate(labels):
            rows = results[i]
            stats[label.lower() + "_count"] = rows[0][0] if rows else 0
        offset = len(labels)
        for j, edge_type in enumerate(edge_types):
            rows = results[offset + j]
            stats[edge_type.lower() + "_count"] = rows[0][0] if rows else 0
        return stats

    async def find_business_flow(self, name: str, k: int = 10) -> QueryResult:
        """Find a business flow and its implementing functions/classes."""
        run = await self._traversal.find_business_flow(name, k)
        rows = run.rows
        return QueryResult(data=list(rows.data), query=run.query, params=run.params)

    async def find_flows_for_function(self, function_name: str) -> QueryResult:
        """Reverse lookup: find business flows that a function belongs to."""
        run = await self._traversal.find_flows_for_function(function_name)
        rows = run.rows
        return QueryResult(data=list(rows.data), query=run.query, params=run.params)

    async def find_related_concepts(self, entity_name: str) -> QueryResult:
        """Find business concepts related to a given entity."""
        run = await self._traversal.find_related_concepts(entity_name)
        rows = run.rows
        return QueryResult(data=list(rows.data), query=run.query, params=run.params)

    async def explore_business_domain(self, category: str) -> QueryResult:
        """Explore all flows and concepts in a business domain."""
        run = await self._traversal.explore_business_domain(category)
        rows = run.rows
        return QueryResult(data=list(rows.data), query=run.query, params=run.params)

    async def find_flow_dependencies(self, flow_name: str) -> QueryResult:
        """Find parent/child flow relationships."""
        run = await self._traversal.find_flow_dependencies(flow_name)
        rows = run.rows
        return QueryResult(data=list(rows.data), query=run.query, params=run.params)

    @staticmethod
    def _public_node(name: str, typ: str, file: str, line: Any) -> dict[str, Any]:
        return {
            "name": name or "",
            "type": typ or "",
            "file": file or "",
            "line": int(line or 0),
        }

    async def traverse_call_chain(
        self,
        repository: str,
        node_name: str,
        direction: str = "callees",
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """MCP: walk CALLS from a Function root; returns root, ordered chain rows, and wiki paths."""
        d = max(1, min(int(max_depth), 5))
        params = {"repository": repository, **make_name_query_params(node_name)}
        root_rows = await self._traversal.traverse_call_chain_root(params)
        if not root_rows.data:
            return {"root": None, "chain": [], "total_nodes": 0}
        rr = root_rows.data[0]
        root_obj = self._public_node(str(rr.get("name", "")), str(rr.get("typ", "")), str(rr.get("file", "")), rr.get("line"))

        crows = await self._traversal.traverse_call_chain_body(params, direction, d)
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in crows.data:
            nm = str(row.get("name", ""))
            key = f"{nm}:{row.get('line', 0)}"
            if key in seen:
                continue
            seen.add(key)
            depth_i = int(row.get("depth", 1) or 1)
            node_obj = self._public_node(nm, str(row.get("typ", "")), str(row.get("file", "")), row.get("line"))
            chain.append(
                {
                    "depth": depth_i,
                    "node": node_obj,
                    "edge_type": "CALLS",
                    "wiki_page_path": str(row.get("wiki_page_path", "") or ""),
                },
            )

        total_nodes = 1 + len(chain)
        return {"root": root_obj, "chain": chain, "total_nodes": total_nodes}

    async def find_impact_scope(
        self,
        repository: str,
        node_name: str,
        max_hops: int = 2,
    ) -> dict[str, Any]:
        """MCP: reverse traversal along CALLS|IMPORTS|INHERITS toward target, grouped by shortest hop."""
        mh = max(1, min(int(max_hops), 3))
        params = {"repository": repository, **make_name_query_params(node_name)}
        tgt_rows = await self._traversal.find_impact_target(params)
        if not tgt_rows.data:
            return {
                "target": None,
                "impact_by_hop": {},
                "affected_wiki_pages": [],
                "total_affected": 0,
            }
        tr = tgt_rows.data[0]
        target_obj = self._public_node(str(tr.get("name", "")), str(tr.get("typ", "")), str(tr.get("file", "")), tr.get("line"))

        wiki_rows = await self._traversal.wiki_paths_by_titles(repository, [str(tr.get("name", "") or "")])
        wiki_dict: dict[str, str] = {}
        for row in wiki_rows.data:
            t = row.get("title")
            p = row.get("path")
            if t and p and t not in wiki_dict:
                wiki_dict[str(t)] = str(p)
        twiki_path = wiki_dict.get(str(tr.get("name", "")), "")

        hop_rows = await self._traversal.find_impact_hops(params, mh)

        titles = list({str(r.get("name", "") or "") for r in hop_rows.data if r.get("name")})
        wiki_extra = await self._traversal.wiki_paths_by_titles(repository, titles)
        for row in wiki_extra.data:
            t = row.get("title")
            p = row.get("path")
            if t and p and str(t) not in wiki_dict:
                wiki_dict[str(t)] = str(p)

        impact_by_hop: dict[str, list[dict[str, Any]]] = {
            "0": [
                {
                    "name": str(tr.get("name", "") or ""),
                    "type": str(tr.get("typ", "") or ""),
                    "wiki_page": twiki_path,
                },
            ],
        }

        affected_pages: set[str] = set()
        if twiki_path:
            affected_pages.add(twiki_path)

        total_marked: set[str] = {str(tr.get("name", "") or "")}

        for row in hop_rows.data:
            nm = str(row.get("name", "") or "")
            hop_i = int(row.get("hop", 1) or 1)
            key = str(hop_i)
            typ = str(row.get("typ", "") or "")
            wp = wiki_dict.get(nm, "")
            if wp:
                affected_pages.add(wp)
            total_marked.add(nm)
            entry = {"name": nm, "type": typ, "wiki_page": wp}
            impact_by_hop.setdefault(key, []).append(entry)

        return {
            "target": target_obj,
            "impact_by_hop": impact_by_hop,
            "affected_wiki_pages": sorted(affected_pages),
            "total_affected": len(total_marked),
        }

    async def analyze_pr_impact(
        self,
        repository: str,
        changed_files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """MCP: map changed files to entities, add one-hop upstream impact, aggregate WikiPage paths."""
        paths = []
        for cf in changed_files:
            p = str(cf.get("path", "")).replace("\\", "/").strip()
            if p:
                paths.append(p)
        if not paths:
            return {
                "affected_pages": [],
                "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
            }

        direct_rows = await self._traversal.analyze_pr_impact_direct(repository, paths)
        if not direct_rows.data:
            return {
                "affected_pages": [],
                "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
            }

        uids = [str(r["uid"]) for r in direct_rows.data if r.get("uid")]
        hop_rows = await self._traversal.analyze_pr_impact_hops(repository, uids)

        all_names: list[str] = []
        for r in direct_rows.data:
            if r.get("name"):
                all_names.append(str(r["name"]))
        for r in hop_rows.data:
            if r.get("name"):
                all_names.append(str(r["name"]))
        wiki_result = await self._traversal.wiki_paths_by_titles(repository, list(set(all_names)))
        wiki_map: dict[str, str] = {}
        for row in wiki_result.data:
            t = row.get("title")
            p = row.get("path")
            if t and p and t not in wiki_map:
                wiki_map[str(t)] = str(p)

        def bucket_for(name: str, file: str) -> str:
            wp = wiki_map.get(name, "")
            return wp if wp else f"file:{file}"

        page_direct: dict[str, int] = defaultdict(int)
        page_entities: dict[str, set[str]] = defaultdict(set)

        for r in direct_rows.data:
            nm = str(r.get("name", "") or "")
            fp = str(r.get("file", "") or "")
            buck = bucket_for(nm, fp)
            page_entities[buck].add(nm)
            page_direct[buck] += 1

        for r in hop_rows.data:
            nm = str(r.get("name", "") or "")
            fp = str(r.get("file", "") or "")
            buck = bucket_for(nm, fp)
            page_entities[buck].add(nm)

        affected_pages: list[dict[str, Any]] = []
        high_count = 0
        medium_count = 0
        for wiki_path, names in sorted(page_entities.items()):
            dc = page_direct.get(wiki_path, 0)
            if dc >= 2:
                level = "high"
                reason = f"{dc} entities directly modified"
                high_count += 1
            elif dc == 1:
                level = "medium"
                reason = "1 entities directly modified"
                medium_count += 1
            else:
                level = "medium"
                reason = "1-hop impact"
                medium_count += 1
            affected_pages.append(
                {
                    "wiki_page_path": wiki_path,
                    "impact_level": level,
                    "reason": reason,
                    "affected_entities": sorted(names),
                },
            )

        return {
            "affected_pages": affected_pages,
            "summary": {
                "high_impact": high_count,
                "medium_impact": medium_count,
                "total_affected_pages": len(affected_pages),
            },
        }

    async def get_p2_stats(self) -> dict[str, Any]:
        """P2 enrichment aggregates for dashboard (architecture, events, RPC, cross-repo)."""
        traversal = self._traversal

        def _cnt(res: object, key: str = "cnt") -> int:
            if not getattr(res, "data", None):
                return 0
            row = res.data[0]
            v = row.get(key, 0)
            return int(v) if v is not None else 0

        architecture_layers: dict[str, int] = {}
        layer_rows = await traversal.p2_architecture_layers()
        for row in layer_rows.data:
            layer = row.get("layer")
            if layer is None:
                continue
            architecture_layers[str(layer)] = int(row.get("cnt") or 0)

        kafka_topics = _cnt(await traversal.p2_kafka_module_count())
        producers = _cnt(await traversal.p2_count_event_produces())
        consumers = _cnt(await traversal.p2_count_event_consumes())

        total_contracts = _cnt(await traversal.p2_count_rpc_contracts())
        contract_methods = _cnt(await traversal.p2_count_rpc_contract_methods())

        cross_repo_call_edges = _cnt(await traversal.p2_count_cross_repo_calls())
        di_dependency_edges = _cnt(await traversal.p2_count_depends_on())
        entity_table_edges = _cnt(await traversal.p2_count_accesses_table())

        return {
            "architecture_layers": architecture_layers,
            "event_tracking": {
                "kafka_topics": kafka_topics,
                "producers": producers,
                "consumers": consumers,
            },
            "rpc_contracts": {
                "total_contracts": total_contracts,
                "contract_methods": contract_methods,
            },
            "cross_repo": {
                "cross_repo_call_edges": cross_repo_call_edges,
                "di_dependency_edges": di_dependency_edges,
                "entity_table_edges": entity_table_edges,
            },
            "quality_overview": None,
        }

    async def expand_node(
        self,
        node_name: str,
        *,
        center_uid: str | None = None,
        limit: int = 20,
        depth: int = 1,
        exclude_uids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Expand a graph node: return new neighbor nodes and edges (progressive graph load).

        When ``center_uid`` is provided the node is resolved directly by uid,
        avoiding ambiguity when multiple entities share the same name.
        Falls back to name/fqn resolution otherwise.
        """
        exclude = list(exclude_uids or [])
        d = max(1, min(int(depth), 3))
        lim = max(1, min(int(limit), 100))

        resolved_uid: str = ""
        if center_uid and str(center_uid).strip():
            resolved_uid = str(center_uid).strip()
        else:
            center_rows = await self._traversal.expand_node_resolve_center(node_name)
            if center_rows.data and center_rows.data[0].get("uid"):
                resolved_uid = str(center_rows.data[0]["uid"])

        if not resolved_uid:
            return {"nodes": [], "edges": [], "center_uid": ""}

        center_uid_resolved = resolved_uid

        n_rows = await self._traversal.expand_node_neighbors(center_uid_resolved, exclude, lim, d)

        nodes_list: list[dict[str, Any]] = []
        for r in n_rows.data:
            uid = r.get("uid", "")
            if not uid:
                continue
            nodes_list.append({
                "id": uid,
                "name": r.get("name", ""),
                "type": r.get("type", ""),
                "file": r.get("file", ""),
                "line": r.get("line", 0),
                "end_line": r.get("end_line"),
                "signature": r.get("signature") or "",
                "docstring": r.get("docstring") or "",
            })

        all_uids = [center_uid_resolved] + [n["id"] for n in nodes_list]
        if len(all_uids) < 2:
            return {"nodes": nodes_list, "edges": [], "center_uid": center_uid_resolved}

        edges_result = await self._traversal.expand_node_edges(all_uids)

        edges_list: list[dict[str, Any]] = []
        edge_keys: set[str] = set()
        for row in edges_result.data:
            src = row.get("source", "")
            tgt = row.get("target", "")
            rtype = row.get("rel_type", "")
            key = f"{src}-{rtype}->{tgt}"
            if key not in edge_keys:
                edge_keys.add(key)
                edges_list.append({"source": src, "target": tgt, "type": rtype})

        return {"nodes": nodes_list, "edges": edges_list, "center_uid": center_uid_resolved}
