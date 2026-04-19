"""Graph traversal queries: call chains, inheritance, dependencies, entity resolution.

All Cypher strings for graph traversals live here; callers use ``GraphQueryService``
as the orchestration layer.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from store.falkordb_store import FalkorDBStore, QueryResultWrapper

_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*)?"
)


def _parse_input(raw: str) -> tuple[str, str | None]:
    """Parse user input which may be a simple name or FQN."""
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


def make_name_query_params(raw: str) -> dict[str, str]:
    """Public alias for :func:`_make_params` (used by services and query helpers)."""
    return _make_params(raw)


def _where_name(alias: str) -> str:
    """Build a WHERE clause that tries fqn first, then falls back to simple name."""
    return f"({alias}.fqn = $fqn OR {alias}.name = $simple_name)"


EXPAND_REL_TYPES = "CALLS|INHERITS|IMPORTS|CONTAINS|PART_OF|REFERENCES"


class TraversalQueryRun(NamedTuple):
    """Result of executing a parameterized traversal query."""

    rows: QueryResultWrapper
    query: str
    params: dict[str, Any]


class TraversalStore:
    """Graph traversal queries: call chains, inheritance, dependencies, entity resolution."""

    def __init__(self, base_store: FalkorDBStore) -> None:
        self._store = base_store

    async def find_call_chain(
        self,
        function_name: str,
        depth: int,
        direction: str,
    ) -> TraversalQueryRun:
        params = _make_params(function_name)
        where = _where_name("f")

        if direction == "upstream":
            query = (
                f"MATCH (f:Function) WHERE {where} "
                "WITH f "
                f"MATCH path = (caller:Function)-[:CALLS*1..{depth}]->(f) "
                "UNWIND relationships(path) AS rel "
                "WITH startNode(rel) AS src, endNode(rel) AS tgt "
                "RETURN DISTINCT src.name AS src_name, src.file AS src_file, "
                "src.start_line AS src_line, src.end_line AS src_end_line, "
                "coalesce(src.fqn, '') AS src_fqn, "
                "tgt.name AS tgt_name, tgt.file AS tgt_file, tgt.start_line AS tgt_line, tgt.end_line AS tgt_end_line, "
                "coalesce(tgt.fqn, '') AS tgt_fqn"
            )
        else:
            query = (
                f"MATCH (f:Function) WHERE {where} "
                "WITH f "
                f"MATCH path = (f)-[:CALLS*1..{depth}]->(callee:Function) "
                "UNWIND relationships(path) AS rel "
                "WITH startNode(rel) AS src, endNode(rel) AS tgt "
                "RETURN DISTINCT src.name AS src_name, src.file AS src_file, "
                "src.start_line AS src_line, src.end_line AS src_end_line, "
                "coalesce(src.fqn, '') AS src_fqn, "
                "tgt.name AS tgt_name, tgt.file AS tgt_file, tgt.start_line AS tgt_line, tgt.end_line AS tgt_end_line, "
                "coalesce(tgt.fqn, '') AS tgt_fqn"
            )
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_inheritance_tree(
        self,
        class_name: str,
        direction: str,
    ) -> TraversalQueryRun:
        params = _make_params(class_name)
        where = _where_name("c")

        if direction == "parents":
            query = (
                f"MATCH (c:Class) WHERE {where} "
                "WITH c "
                "MATCH (c)-[:INHERITS*1..10]->(parent:Class) "
                "RETURN parent.name AS name, parent.file AS file, "
                "parent.start_line AS start_line, parent.end_line AS end_line"
            )
        else:
            query = (
                f"MATCH (c:Class) WHERE {where} "
                "WITH c "
                "MATCH (child:Class)-[:INHERITS*1..10]->(c) "
                "RETURN child.name AS name, child.file AS file, "
                "child.start_line AS start_line, child.end_line AS end_line"
            )
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_class_methods(self, class_name: str) -> TraversalQueryRun:
        params = _make_params(class_name)
        where = _where_name("c")

        query = (
            f"MATCH (c:Class) WHERE {where} "
            "WITH c "
            "MATCH (c)-[:CONTAINS]->(m:Function) "
            "RETURN m.name AS name, m.signature AS signature, m.file AS file, "
            "m.start_line AS start_line, m.end_line AS end_line "
            "ORDER BY start_line"
        )
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_module_dependencies(self, module_name: str) -> TraversalQueryRun:
        params = _make_params(module_name)
        where = _where_name("m")

        query = (
            f"MATCH (m:Module) WHERE {where} "
            "WITH m "
            "MATCH (m)-[:IMPORTS]->(dep:Module) "
            "RETURN dep.name AS name, dep.path AS path"
        )
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_reverse_dependencies(self, module_name: str) -> TraversalQueryRun:
        params = _make_params(module_name)
        where = _where_name("dep")

        query = (
            f"MATCH (dep:Module) WHERE {where} "
            "WITH dep "
            "MATCH (m:Module)-[:IMPORTS]->(dep) "
            "RETURN m.name AS name, m.path AS path"
        )
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_entity(self, name: str, entity_type: str) -> TraversalQueryRun:
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
        return TraversalQueryRun(rows, query, params)

    async def find_file_entities(self, file_path: str) -> TraversalQueryRun:
        query = (
            "MATCH (n {file: $file}) "
            "WHERE n:Function OR n:Class "
            "RETURN n.name AS name, labels(n)[0] AS type, n.start_line AS line, "
            "coalesce(n.signature, '') AS signature "
            "ORDER BY n.start_line"
        )
        params: dict[str, Any] = {"file": file_path}
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def count_nodes_by_label(self, label: str) -> QueryResultWrapper:
        return await self._store.execute_query(f"MATCH (n:{label}) RETURN count(n) AS cnt")

    async def count_edges_by_type(self, edge_type: str) -> QueryResultWrapper:
        return await self._store.execute_query(f"MATCH ()-[r:{edge_type}]->() RETURN count(r) AS cnt")

    async def find_business_flow(self, name: str, k: int) -> TraversalQueryRun:
        query = (
            "MATCH (bf:BusinessFlow)-[r:IMPLEMENTS]->(n) "
            "WHERE bf.name CONTAINS $name "
            "RETURN bf, r, n ORDER BY r.step_order LIMIT $k"
        )
        params = {"name": name, "k": k}
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_flows_for_function(self, function_name: str) -> TraversalQueryRun:
        params = _make_params(function_name)
        where = _where_name("f")
        query = (
            f"MATCH (bf:BusinessFlow)-[:IMPLEMENTS]->(f:Function) "
            f"WHERE {where} RETURN bf, f"
        )
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_related_concepts(self, entity_name: str) -> TraversalQueryRun:
        query = (
            "MATCH (bc:BusinessConcept)-[r:RELATES_TO]->(n) "
            "WHERE n.name = $name "
            "RETURN bc, r, n ORDER BY r.relevance_score DESC"
        )
        params = {"name": entity_name}
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def explore_business_domain(self, category: str) -> TraversalQueryRun:
        query = (
            "MATCH (bf:BusinessFlow) WHERE bf.category = $category "
            "OPTIONAL MATCH (bf)-[:IMPLEMENTS]->(f) "
            "RETURN bf, collect(f) AS functions"
        )
        params = {"category": category}
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def find_flow_dependencies(self, flow_name: str) -> TraversalQueryRun:
        query = (
            "MATCH path=(bf:BusinessFlow)-[:PART_OF*0..3]->(parent:BusinessFlow) "
            "WHERE bf.name CONTAINS $name "
            "RETURN bf, parent, length(path) AS depth ORDER BY depth"
        )
        params = {"name": flow_name}
        rows = await self._store.execute_query(query, params)
        return TraversalQueryRun(rows, query, params)

    async def wiki_paths_by_titles(self, repository: str, titles: list[str]) -> QueryResultWrapper:
        titles = [t for t in titles if t]
        if not titles:
            return QueryResultWrapper(data=[], raw=[])
        q = (
            "UNWIND $titles AS t "
            "MATCH (wp:WikiPage {repository: $repository}) "
            "WHERE wp.title = t "
            "RETURN DISTINCT t AS title, wp.path AS path"
        )
        return await self._store.execute_query(q, {"repository": repository, "titles": titles})

    async def traverse_call_chain_root(self, params: dict[str, str]) -> QueryResultWrapper:
        where = _where_name("root")
        root_q = (
            f"MATCH (root:Function) WHERE root.repository = $repository AND {where} "
            "RETURN root.name AS name, labels(root)[0] AS typ, root.file AS file, root.start_line AS line LIMIT 1"
        )
        return await self._store.execute_query(root_q, params)

    async def traverse_call_chain_body(
        self,
        params: dict[str, str],
        direction: str,
        depth: int,
    ) -> QueryResultWrapper:
        where = _where_name("root")
        if direction == "callers":
            chain_q = (
                f"MATCH (root:Function) WHERE root.repository = $repository AND {where} "
                f"MATCH path = (caller:Function)-[:CALLS*1..{depth}]->(root) "
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
                f"MATCH path = (root)-[:CALLS*1..{depth}]->(fn:Function) "
                "WITH fn, min(length(path)) AS depth "
                "OPTIONAL MATCH (wp:WikiPage {repository: $repository}) "
                "WHERE wp.title = fn.name "
                "RETURN fn.name AS name, labels(fn)[0] AS typ, fn.file AS file, "
                "fn.start_line AS line, depth, coalesce(wp.path, '') AS wiki_page_path "
                "ORDER BY depth, name"
            )
        return await self._store.execute_query(chain_q, params)

    async def find_impact_target(self, params: dict[str, str]) -> QueryResultWrapper:
        tgt_where = _where_name("target")
        tgt_q = (
            "MATCH (target) WHERE (target:Function OR target:Class OR target:Module) "
            f"AND target.repository = $repository AND {tgt_where} "
            "RETURN target.name AS name, labels(target)[0] AS typ, target.file AS file, "
            "target.start_line AS line LIMIT 1"
        )
        return await self._store.execute_query(tgt_q, params)

    async def find_impact_hops(self, params: dict[str, str], max_hops: int) -> QueryResultWrapper:
        tgt_where = _where_name("target")
        hop_q = (
            "MATCH (target) WHERE (target:Function OR target:Class OR target:Module) "
            f"AND target.repository = $repository AND {tgt_where} "
            f"MATCH p = (n)-[:CALLS|IMPORTS|INHERITS*1..{max_hops}]->(target) "
            "WHERE id(n) <> id(target) "
            "WITH n, min(length(p)) AS hop "
            "RETURN DISTINCT n.name AS name, labels(n)[0] AS typ, hop "
            "ORDER BY hop, name"
        )
        return await self._store.execute_query(hop_q, params)

    async def analyze_pr_impact_direct(self, repository: str, paths: list[str]) -> QueryResultWrapper:
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
        return await self._store.execute_query(match_q, {"repository": repository, "paths": paths})

    async def analyze_pr_impact_hops(self, repository: str, uids: list[str]) -> QueryResultWrapper:
        hop_q = (
            "UNWIND $uids AS uid "
            "MATCH (entity) WHERE entity.uid = uid AND entity.repository = $repository "
            "MATCH (hop)-[:CALLS|IMPORTS|INHERITS]->(entity) "
            "WHERE hop.repository = $repository "
            "RETURN DISTINCT hop.uid AS uid, hop.name AS name, hop.file AS file, labels(hop)[0] AS typ"
        )
        return await self._store.execute_query(hop_q, {"repository": repository, "uids": uids})

    async def p2_architecture_layers(self) -> QueryResultWrapper:
        return await self._store.execute_query(
            "MATCH (c:Class) WHERE c.architecture_layer IS NOT NULL "
            "RETURN c.architecture_layer AS layer, count(c) AS cnt",
        )

    async def p2_kafka_module_count(self) -> QueryResultWrapper:
        return await self._store.execute_query(
            "MATCH (m:Module) WHERE m.language = 'kafka' RETURN count(m) AS cnt",
        )

    async def p2_count_event_produces(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:EVENT_PRODUCES]->() RETURN count(r) AS cnt")

    async def p2_count_event_consumes(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:EVENT_CONSUMES]->() RETURN count(r) AS cnt")

    async def p2_count_rpc_contracts(self) -> QueryResultWrapper:
        return await self._store.execute_query(
            "MATCH (c:Class) WHERE c.is_rpc_contract = true RETURN count(c) AS cnt",
        )

    async def p2_count_rpc_contract_methods(self) -> QueryResultWrapper:
        return await self._store.execute_query(
            "MATCH (c:Class)-[:CONTAINS]->(m:Function) "
            "WHERE coalesce(c.is_rpc_contract, false) = true "
            "RETURN count(m) AS cnt",
        )

    async def p2_count_cross_repo_calls(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:CROSS_REPO_CALLS]->() RETURN count(r) AS cnt")

    async def p2_count_depends_on(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:DEPENDS_ON]->() RETURN count(r) AS cnt")

    async def p2_count_accesses_table(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:ACCESSES_TABLE]->() RETURN count(r) AS cnt")

    async def expand_node_resolve_center(self, name: str) -> QueryResultWrapper:
        center_q = (
            "MATCH (center) "
            "WHERE (center:Function OR center:Class OR center:Module) "
            "AND (center.name = $name OR center.fqn = $name) "
            "RETURN center.uid AS uid LIMIT 1"
        )
        return await self._store.execute_query(center_q, {"name": name})

    async def expand_node_neighbors(
        self,
        center_uid: str,
        exclude_uids: list[str],
        limit: int,
        depth: int,
    ) -> QueryResultWrapper:
        rel_pat = EXPAND_REL_TYPES
        neighbor_q = (
            f"MATCH (center) WHERE center.uid = $center_uid "
            f"MATCH path = (center)-[:{rel_pat}*1..{depth}]-(nbr) "
            "WHERE (nbr:Function OR nbr:Class OR nbr:Module) "
            "AND NOT coalesce(nbr.uid, '') IN $exclude_uids "
            "WITH DISTINCT nbr "
            "LIMIT $limit "
            "RETURN nbr.uid AS uid, nbr.name AS name, labels(nbr)[0] AS type, "
            "coalesce(nbr.file, '') AS file, coalesce(nbr.start_line, 0) AS line, "
            "coalesce(nbr.end_line, nbr.start_line, 0) AS end_line, "
            "coalesce(nbr.signature, '') AS signature, "
            "coalesce(nbr.docstring, '') AS docstring"
        )
        return await self._store.execute_query(
            neighbor_q,
            {"center_uid": center_uid, "exclude_uids": exclude_uids, "limit": limit},
        )

    async def expand_node_edges(self, uids: list[str]) -> QueryResultWrapper:
        edges_q = (
            "MATCH (a)-[rel]->(b) "
            "WHERE a.uid IN $uids AND b.uid IN $uids "
            "RETURN a.uid AS source, b.uid AS target, type(rel) AS rel_type"
        )
        return await self._store.execute_query(edges_q, {"uids": uids})

    _ENTITY_DETAILS_RETURN = (
        "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, n.file AS file, "
        "n.start_line AS start_line, n.end_line AS end_line, "
        "coalesce(n.code_snippet, '') AS code_snippet, coalesce(n.docstring, '') AS docstring, "
        "coalesce(n.signature, '') AS signature, coalesce(n.repository, '') AS repository "
        "LIMIT 1"
    )

    async def load_entity_details_by_uid(self, uid: str) -> QueryResultWrapper:
        q = f"MATCH (n) WHERE n.uid = $uid {self._ENTITY_DETAILS_RETURN}"
        return await self._store.execute_query(q, {"uid": uid})

    async def load_entity_details_by_name(
        self,
        name: str,
        repository: str | None,
    ) -> QueryResultWrapper:
        params: dict[str, Any] = {"name": name}
        repo_clause = ""
        if repository:
            params["repo"] = repository.strip()
            repo_clause = "AND n.repository = $repo "
        q = (
            f"MATCH (n) WHERE (n:Function OR n:Class) AND (n.name = $name OR n.fqn ENDS WITH $name) "
            f"{repo_clause} {self._ENTITY_DETAILS_RETURN}"
        )
        return await self._store.execute_query(q, params)

    async def wiki_bundle_scoped(self, repository: str, needle: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage {repository: $repository}) "
            "WHERE wp.title CONTAINS $needle OR wp.path CONTAINS $needle "
            "RETURN wp.title AS title, wp.path AS path, coalesce(wp.content, '') AS content "
            "LIMIT 5"
        )
        return await self._store.execute_query(
            q, {"repository": repository.strip(), "needle": needle},
        )

    async def wiki_bundle_global(self, needle: str) -> QueryResultWrapper:
        q = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.title CONTAINS $needle OR wp.path CONTAINS $needle "
            "RETURN wp.title AS title, wp.path AS path, coalesce(wp.content, '') AS content "
            "LIMIT 5"
        )
        return await self._store.execute_query(q, {"needle": needle})
