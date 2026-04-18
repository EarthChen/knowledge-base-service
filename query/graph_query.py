"""Graph query interface — parameterized Cypher templates for code analysis.

Provides pre-built Cypher query templates for common code analysis tasks:
call chains, inheritance trees, module dependencies, and entity lookups.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from log import get_logger
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*)?"
)


def _parse_input(raw: str) -> tuple[str, str | None]:
    """Parse user input which may be a simple name or FQN.

    Returns (simple_name, fqn_or_none).
    For ``com.foo.Bar#doStuff`` returns (``doStuff``, ``com.foo.Bar#doStuff``).
    For ``com.foo.Bar`` returns (``Bar``, ``com.foo.Bar``).
    For ``loginV2`` returns (``loginV2``, None).
    """
    if _FQN_RE.fullmatch(raw.strip()):
        fqn = raw.strip()
        if "#" in fqn:
            simple = fqn.rsplit("#", 1)[1]
        else:
            simple = fqn.rsplit(".", 1)[-1]
        return simple, fqn
    return raw.strip(), None


def _make_params(raw: str) -> dict[str, str]:
    """Build query params with both fqn and simple_name for fallback matching."""
    simple, fqn = _parse_input(raw)
    return {"fqn": fqn or simple, "simple_name": simple}


def _where_name(alias: str) -> str:
    """Build a WHERE clause that tries fqn first, then falls back to simple name."""
    return f"({alias}.fqn = $fqn OR {alias}.name = $simple_name)"


@dataclass
class QueryResult:
    data: list[dict[str, Any]]
    query: str
    params: dict[str, Any]


class GraphQueryService:
    """Provides parameterized Cypher graph queries over the code knowledge graph."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def find_call_chain(
        self, function_name: str, depth: int = 3, direction: str = "downstream",
    ) -> QueryResult:
        """Find the call chain starting from a function.

        Accepts simple name (``loginV2``) or FQN (``com.foo.Bar#loginV2``).
        Returns nodes and edges for multi-level visualization.
        """
        params = _make_params(function_name)
        where = _where_name("f")

        if direction == "upstream":
            query = (
                f"MATCH (f:Function) WHERE {where} "
                "WITH f "
                f"MATCH path = (caller:Function)-[:CALLS*1..{depth}]->(f) "
                "UNWIND relationships(path) AS rel "
                "WITH startNode(rel) AS src, endNode(rel) AS tgt "
                "RETURN DISTINCT src.name AS src_name, src.file AS src_file, src.start_line AS src_line, "
                "coalesce(src.fqn, '') AS src_fqn, "
                "tgt.name AS tgt_name, tgt.file AS tgt_file, tgt.start_line AS tgt_line, "
                "coalesce(tgt.fqn, '') AS tgt_fqn"
            )
        else:
            query = (
                f"MATCH (f:Function) WHERE {where} "
                "WITH f "
                f"MATCH path = (f)-[:CALLS*1..{depth}]->(callee:Function) "
                "UNWIND relationships(path) AS rel "
                "WITH startNode(rel) AS src, endNode(rel) AS tgt "
                "RETURN DISTINCT src.name AS src_name, src.file AS src_file, src.start_line AS src_line, "
                "coalesce(src.fqn, '') AS src_fqn, "
                "tgt.name AS tgt_name, tgt.file AS tgt_file, tgt.start_line AS tgt_line, "
                "coalesce(tgt.fqn, '') AS tgt_fqn"
            )
        rows = await self._store.execute_query(query, params)

        nodes_map: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []

        for r in rows.data:
            src_key = f"{r.get('src_name', '')}:{r.get('src_line', 0)}"
            tgt_key = f"{r.get('tgt_name', '')}:{r.get('tgt_line', 0)}"
            if src_key not in nodes_map:
                nodes_map[src_key] = {
                    "name": r.get("src_name", ""),
                    "file": r.get("src_file", ""),
                    "line": r.get("src_line", 0),
                    "fqn": r.get("src_fqn", ""),
                }
            if tgt_key not in nodes_map:
                nodes_map[tgt_key] = {
                    "name": r.get("tgt_name", ""),
                    "file": r.get("tgt_file", ""),
                    "line": r.get("tgt_line", 0),
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
        params = _make_params(class_name)
        where = _where_name("c")

        if direction == "parents":
            query = (
                f"MATCH (c:Class) WHERE {where} "
                "WITH c "
                "MATCH (c)-[:INHERITS*1..10]->(parent:Class) "
                "RETURN parent.name AS name, parent.file AS file, parent.start_line AS line"
            )
        else:
            query = (
                f"MATCH (c:Class) WHERE {where} "
                "WITH c "
                "MATCH (child:Class)-[:INHERITS*1..10]->(c) "
                "RETURN child.name AS name, child.file AS file, child.start_line AS line"
            )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "file": r[1], "line": r[2]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_class_methods(self, class_name: str) -> QueryResult:
        """Find all methods belonging to a class. Accepts simple name or FQN."""
        params = _make_params(class_name)
        where = _where_name("c")

        query = (
            f"MATCH (c:Class) WHERE {where} "
            "WITH c "
            "MATCH (c)-[:CONTAINS]->(m:Function) "
            "RETURN m.name AS name, m.signature AS signature, m.file AS file, m.start_line AS line "
            "ORDER BY m.start_line"
        )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "signature": r[1], "file": r[2], "line": r[3]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_module_dependencies(self, module_name: str) -> QueryResult:
        """Find what a module imports."""
        params = _make_params(module_name)
        where = _where_name("m")

        query = (
            f"MATCH (m:Module) WHERE {where} "
            "WITH m "
            "MATCH (m)-[:IMPORTS]->(dep:Module) "
            "RETURN dep.name AS name, dep.path AS path"
        )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_reverse_dependencies(self, module_name: str) -> QueryResult:
        """Find what modules import this module."""
        params = _make_params(module_name)
        where = _where_name("dep")

        query = (
            f"MATCH (dep:Module) WHERE {where} "
            "WITH dep "
            "MATCH (m:Module)-[:IMPORTS]->(dep) "
            "RETURN m.name AS name, m.path AS path"
        )
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "path": r[1]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def find_entity(self, name: str, entity_type: str = "any") -> QueryResult:
        """Find a code entity by name or FQN."""
        params = _make_params(name)
        where = _where_name("n")

        if entity_type == "function":
            query = (
                f"MATCH (n:Function) WHERE {where} "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "n.signature AS signature, n.docstring AS docstring, 'Function' AS type"
            )
        elif entity_type == "class":
            query = (
                f"MATCH (n:Class) WHERE {where} "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "'' AS signature, n.docstring AS docstring, 'Class' AS type"
            )
        else:
            query = (
                "MATCH (n) "
                f"WHERE (n:Function OR n:Class OR n:Module) AND {where} "
                "RETURN n.name AS name, n.file AS file, n.start_line AS line, "
                "coalesce(n.signature, '') AS signature, "
                "coalesce(n.docstring, '') AS docstring, labels(n)[0] AS type"
            )
        rows = await self._store.execute_query(query, params)
        data = [
            {"name": r[0], "file": r[1], "line": r[2], "signature": r[3], "docstring": r[4], "type": r[5]}
            for r in rows
        ]
        return QueryResult(data=data, query=query, params=params)

    async def find_file_entities(self, file_path: str) -> QueryResult:
        """Find all entities defined in a file."""
        query = (
            "MATCH (n {file: $file}) "
            "WHERE n:Function OR n:Class "
            "RETURN n.name AS name, labels(n)[0] AS type, n.start_line AS line, "
            "coalesce(n.signature, '') AS signature "
            "ORDER BY n.start_line"
        )
        params = {"file": file_path}
        rows = await self._store.execute_query(query, params)
        data = [{"name": r[0], "type": r[1], "line": r[2], "signature": r[3]} for r in rows]
        return QueryResult(data=data, query=query, params=params)

    async def execute_raw(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Execute a raw Cypher query."""
        rows = await self._store.execute_query(cypher, params)
        data = [{"row": list(r)} for r in rows]
        return QueryResult(data=data, query=cypher, params=params or {})

    async def get_graph_stats(self) -> dict[str, int]:
        """Get statistics about the knowledge graph."""
        stats: dict[str, int] = {}
        for label in ("Function", "Class", "Module", "Document"):
            rows = await self._store.execute_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            stats[label.lower() + "_count"] = rows[0][0] if rows else 0

        for edge_type in ("CALLS", "INHERITS", "IMPORTS", "CONTAINS", "REFERENCES"):
            rows = await self._store.execute_query(f"MATCH ()-[r:{edge_type}]->() RETURN count(r) AS cnt")
            stats[edge_type.lower() + "_count"] = rows[0][0] if rows else 0

        return stats

    async def find_business_flow(self, name: str, k: int = 10) -> QueryResult:
        """Find a business flow and its implementing functions/classes."""
        query = (
            "MATCH (bf:BusinessFlow)-[r:IMPLEMENTS]->(n) "
            "WHERE bf.name CONTAINS $name "
            "RETURN bf, r, n ORDER BY r.step_order LIMIT $k"
        )
        params = {"name": name, "k": k}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def find_flows_for_function(self, function_name: str) -> QueryResult:
        """Reverse lookup: find business flows that a function belongs to."""
        params = _make_params(function_name)
        where = _where_name("f")
        query = (
            f"MATCH (bf:BusinessFlow)-[:IMPLEMENTS]->(f:Function) "
            f"WHERE {where} RETURN bf, f"
        )
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def find_related_concepts(self, entity_name: str) -> QueryResult:
        """Find business concepts related to a given entity."""
        query = (
            "MATCH (bc:BusinessConcept)-[r:RELATES_TO]->(n) "
            "WHERE n.name = $name "
            "RETURN bc, r, n ORDER BY r.relevance_score DESC"
        )
        params = {"name": entity_name}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def explore_business_domain(self, category: str) -> QueryResult:
        """Explore all flows and concepts in a business domain."""
        query = (
            "MATCH (bf:BusinessFlow) WHERE bf.category = $category "
            "OPTIONAL MATCH (bf)-[:IMPLEMENTS]->(f) "
            "RETURN bf, collect(f) AS functions"
        )
        params = {"category": category}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def find_flow_dependencies(self, flow_name: str) -> QueryResult:
        """Find parent/child flow relationships."""
        query = (
            "MATCH path=(bf:BusinessFlow)-[:PART_OF*0..3]->(parent:BusinessFlow) "
            "WHERE bf.name CONTAINS $name "
            "RETURN bf, parent, length(path) AS depth ORDER BY depth"
        )
        params = {"name": flow_name}
        rows = await self._store.execute_query(query, params)
        return QueryResult(data=list(rows.data), query=query, params=params)

    async def _wiki_paths_by_titles(self, repository: str, titles: list[str]) -> dict[str, str]:
        """Resolve WikiPage.path by title (batch)."""
        titles = [t for t in titles if t]
        if not titles:
            return {}
        q = (
            "UNWIND $titles AS t "
            "MATCH (wp:WikiPage {repository: $repository}) "
            "WHERE wp.title = t "
            "RETURN DISTINCT t AS title, wp.path AS path"
        )
        rows = await self._store.execute_query(q, {"repository": repository, "titles": titles})
        out: dict[str, str] = {}
        for row in rows.data:
            t = row.get("title")
            p = row.get("path")
            if t and p and t not in out:
                out[str(t)] = str(p)
        return out

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
        params = {"repository": repository, **_make_params(node_name)}
        where = _where_name("root")
        root_q = (
            f"MATCH (root:Function) WHERE root.repository = $repository AND {where} "
            "RETURN root.name AS name, labels(root)[0] AS typ, root.file AS file, root.start_line AS line LIMIT 1"
        )
        root_rows = await self._store.execute_query(root_q, params)
        if not root_rows.data:
            return {"root": None, "chain": [], "total_nodes": 0}
        rr = root_rows.data[0]
        root_obj = self._public_node(str(rr.get("name", "")), str(rr.get("typ", "")), str(rr.get("file", "")), rr.get("line"))

        if direction == "callers":
            chain_q = (
                f"MATCH (root:Function) WHERE root.repository = $repository AND {where} "
                f"MATCH path = (caller:Function)-[:CALLS*1..{d}]->(root) "
                "WITH caller, min(length(path)) AS depth "
                "OPTIONAL MATCH (wp:WikiPage {repository: $repository}) "
                "WHERE wp.title = caller.name "
                "RETURN caller.name AS name, labels(caller)[0] AS typ, caller.file AS file, "
                "caller.start_line AS line, depth, coalesce(wp.path, '') AS wiki_page_path "
                "ORDER BY depth, name"
            )
        else:
            chain_q = (
                f"MATCH (root:Function) WHERE root.repository = $repository AND {where} "
                f"MATCH path = (root)-[:CALLS*1..{d}]->(fn:Function) "
                "WITH fn, min(length(path)) AS depth "
                "OPTIONAL MATCH (wp:WikiPage {repository: $repository}) "
                "WHERE wp.title = fn.name "
                "RETURN fn.name AS name, labels(fn)[0] AS typ, fn.file AS file, "
                "fn.start_line AS line, depth, coalesce(wp.path, '') AS wiki_page_path "
                "ORDER BY depth, name"
            )

        crows = await self._store.execute_query(chain_q, params)
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
        params = {"repository": repository, **_make_params(node_name)}
        tgt_where = _where_name("target")
        tgt_q = (
            "MATCH (target) WHERE (target:Function OR target:Class OR target:Module) "
            f"AND target.repository = $repository AND {tgt_where} "
            "RETURN target.name AS name, labels(target)[0] AS typ, target.file AS file, "
            "target.start_line AS line LIMIT 1"
        )
        tgt_rows = await self._store.execute_query(tgt_q, params)
        if not tgt_rows.data:
            return {
                "target": None,
                "impact_by_hop": {},
                "affected_wiki_pages": [],
                "total_affected": 0,
            }
        tr = tgt_rows.data[0]
        target_obj = self._public_node(str(tr.get("name", "")), str(tr.get("typ", "")), str(tr.get("file", "")), tr.get("line"))

        wiki_map = await self._wiki_paths_by_titles(repository, [str(tr.get("name", "") or "")])
        twiki = wiki_map.get(str(tr.get("name", "")), "")

        hop_q = (
            "MATCH (target) WHERE (target:Function OR target:Class OR target:Module) "
            f"AND target.repository = $repository AND {tgt_where} "
            f"MATCH p = (n)-[:CALLS|IMPORTS|INHERITS*1..{mh}]->(target) "
            "WHERE id(n) <> id(target) "
            "WITH n, min(length(p)) AS hop "
            "RETURN DISTINCT n.name AS name, labels(n)[0] AS typ, hop "
            "ORDER BY hop, name"
        )
        hop_rows = await self._store.execute_query(hop_q, params)

        titles = list({str(r.get("name", "") or "") for r in hop_rows.data if r.get("name")})
        wiki_extra = await self._wiki_paths_by_titles(repository, titles)
        wiki_map.update(wiki_extra)

        impact_by_hop: dict[str, list[dict[str, Any]]] = {
            "0": [
                {
                    "name": str(tr.get("name", "") or ""),
                    "type": str(tr.get("typ", "") or ""),
                    "wiki_page": twiki,
                },
            ],
        }

        affected_pages: set[str] = set()
        if twiki:
            affected_pages.add(twiki)

        total_marked: set[str] = {str(tr.get("name", "") or "")}

        for row in hop_rows.data:
            nm = str(row.get("name", "") or "")
            hop_i = int(row.get("hop", 1) or 1)
            key = str(hop_i)
            typ = str(row.get("typ", "") or "")
            wp = wiki_map.get(nm, "")
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

        match_q = (
            "UNWIND $paths AS fp "
            "MATCH (n) "
            "WHERE n.repository = $repository AND (n:Function OR n:Class) "
            "AND ( "
            "  replace(n.file, '\\\\', '/') = fp "
            "  OR replace(n.file, '\\\\', '/') ENDS WITH '/' + fp "
            "  OR replace(n.file, '\\\\', '/') ENDS WITH fp "
            ") "
            "RETURN DISTINCT n.uid AS uid, n.name AS name, n.file AS file"
        )
        direct_rows = await self._store.execute_query(match_q, {"repository": repository, "paths": paths})
        if not direct_rows.data:
            return {
                "affected_pages": [],
                "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
            }

        uids = [str(r["uid"]) for r in direct_rows.data if r.get("uid")]
        hop_q = (
            "UNWIND $uids AS uid "
            "MATCH (entity) WHERE entity.uid = uid AND entity.repository = $repository "
            "MATCH (hop)-[:CALLS|IMPORTS|INHERITS]->(entity) "
            "WHERE hop.repository = $repository "
            "RETURN DISTINCT hop.uid AS uid, hop.name AS name, hop.file AS file, labels(hop)[0] AS typ"
        )
        hop_rows = await self._store.execute_query(hop_q, {"repository": repository, "uids": uids})

        all_names: list[str] = []
        for r in direct_rows.data:
            if r.get("name"):
                all_names.append(str(r["name"]))
        for r in hop_rows.data:
            if r.get("name"):
                all_names.append(str(r["name"]))
        wiki_map = await self._wiki_paths_by_titles(repository, list(set(all_names)))

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
        store = self._store

        def _cnt(res: object, key: str = "cnt") -> int:
            if not getattr(res, "data", None):
                return 0
            row = res.data[0]
            v = row.get(key, 0)
            return int(v) if v is not None else 0

        architecture_layers: dict[str, int] = {}
        layer_rows = await store.execute_query(
            "MATCH (c:Class) WHERE c.architecture_layer IS NOT NULL "
            "RETURN c.architecture_layer AS layer, count(c) AS cnt"
        )
        for row in layer_rows.data:
            layer = row.get("layer")
            if layer is None:
                continue
            architecture_layers[str(layer)] = int(row.get("cnt") or 0)

        kafka_topics = _cnt(
            await store.execute_query(
                "MATCH (m:Module) WHERE m.language = 'kafka' RETURN count(m) AS cnt"
            )
        )
        producers = _cnt(
            await store.execute_query("MATCH ()-[r:EVENT_PRODUCES]->() RETURN count(r) AS cnt")
        )
        consumers = _cnt(
            await store.execute_query("MATCH ()-[r:EVENT_CONSUMES]->() RETURN count(r) AS cnt")
        )

        total_contracts = _cnt(
            await store.execute_query(
                "MATCH (c:Class) WHERE c.is_rpc_contract = true RETURN count(c) AS cnt"
            )
        )
        contract_methods = _cnt(
            await store.execute_query(
                "MATCH (c:Class)-[:CONTAINS]->(m:Function) "
                "WHERE coalesce(c.is_rpc_contract, false) = true "
                "RETURN count(m) AS cnt"
            )
        )

        cross_repo_call_edges = _cnt(
            await store.execute_query("MATCH ()-[r:CROSS_REPO_CALLS]->() RETURN count(r) AS cnt")
        )
        di_dependency_edges = _cnt(
            await store.execute_query("MATCH ()-[r:DEPENDS_ON]->() RETURN count(r) AS cnt")
        )
        entity_table_edges = _cnt(
            await store.execute_query("MATCH ()-[r:ACCESSES_TABLE]->() RETURN count(r) AS cnt")
        )

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
