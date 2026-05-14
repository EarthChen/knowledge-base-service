"""Analysis-oriented Cypher: blast radius, communities, insights, impact, endpoints, agent workflow."""

from __future__ import annotations

from typing import Any

from store.falkordb_store import FalkorDBStore, QueryResultWrapper
from store.traversal_store import make_name_query_params

# Graph insights — distinct markers (tests / debugging).
_GRAPH_REPOS_PARAM = "repos"
_Q_RESOLVE_REPOS = "__GRAPH_INSIGHTS_RESOLVE_REPOS_FROM_WIKI__"
_Q_STATS = "__GRAPH_INSIGHTS_Q_STATS__"
_Q_ISOLATED = "__GRAPH_INSIGHTS_Q_ISOLATED__"
_Q_CYCLES = "__GRAPH_INSIGHTS_Q_CYCLES__"
_Q_CROSS_LAYER = "__GRAPH_INSIGHTS_Q_CROSS_LAYER__"
_Q_COHESION = "__GRAPH_INSIGHTS_Q_COHESION__"
_Q_BRIDGE = "__GRAPH_INSIGHTS_Q_BRIDGE__"


class AnalysisStore:
    """Analysis queries: blast radius, community detection, insights, impact, endpoints, agent workflows."""

    def __init__(self, base_store: FalkorDBStore) -> None:
        self._store = base_store

    # ─── blast_radius ─────────────────────────────────────────────────────────

    async def resolve_entity(self, raw_name: str, repository: str | None) -> QueryResultWrapper:
        params = {**make_name_query_params(raw_name), "repository": repository}
        query = (
            "MATCH (n) WHERE (n:Function OR n:Class OR n:Module) "
            "AND (n.fqn = $fqn OR n.name = $simple_name) "
            "AND ($repository IS NULL OR n.repository = $repository) "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS typ, "
            "coalesce(n.file, '') AS file, coalesce(n.start_line, 0) AS line"
        )
        return await self._store.execute_query(query, params)

    async def find_incoming_neighbors(self, uids: list[str], repository: str | None) -> QueryResultWrapper:
        query = (
            "UNWIND $uids AS uid "
            "MATCH (entity {uid: uid}) "
            "MATCH (nbr)-[r:CALLS|IMPORTS|INHERITS]->(entity) "
            "WHERE ($repository IS NULL OR (entity.repository = $repository AND nbr.repository = $repository)) "
            "RETURN DISTINCT nbr.uid AS uid, nbr.name AS name, labels(nbr)[0] AS typ, "
            "coalesce(nbr.file, '') AS file, coalesce(nbr.start_line, 0) AS line, type(r) AS relation"
        )
        return await self._store.execute_query(
            query,
            {"uids": uids, "repository": repository},
        )

    async def hydrate_nodes(self, uids: list[str], repository: str | None) -> QueryResultWrapper:
        query = (
            "UNWIND $uids AS uid "
            "MATCH (n {uid: uid}) "
            "WHERE $repository IS NULL OR n.repository = $repository "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS typ, "
            "coalesce(n.file, '') AS file, coalesce(n.start_line, 0) AS line"
        )
        return await self._store.execute_query(query, {"uids": uids, "repository": repository})

    # ─── community_detection ──────────────────────────────────────────────────

    async def fetch_community_nodes(self, repository: str | None) -> QueryResultWrapper:
        nodes_q = """
            MATCH (n)
            WHERE (n:Function OR n:Class)
            AND ($repository IS NULL OR n.repository = $repository)
            /* community_nodes */
            RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS typ,
            coalesce(n.file, '') AS file
        """
        return await self._store.execute_query(nodes_q, {"repository": repository})

    async def fetch_community_edges(self, repository: str | None) -> QueryResultWrapper:
        edges_q = """
            MATCH (a)-[r:CALLS|INHERITS|IMPORTS]->(b)
            WHERE (a:Function OR a:Class) AND (b:Function OR b:Class)
            AND ($repository IS NULL OR (a.repository = $repository AND b.repository = $repository))
            /* community_edges */
            RETURN a.uid AS src, b.uid AS tgt
        """
        return await self._store.execute_query(edges_q, {"repository": repository})

    # ─── graph_insights ───────────────────────────────────────────────────────

    async def resolve_code_repositories_from_business_wiki(self, business_id: str) -> QueryResultWrapper:
        cypher = f"""
// {_Q_RESOLVE_REPOS}
MATCH (ws:WikiSpace {{business_id: $business_id}})-[:HAS_CHILD*1..10]->(wp:WikiPage)
WITH collect(DISTINCT wp.repository) AS raw_repos
WITH [r IN raw_repos WHERE r IS NOT NULL AND r <> '' AND r <> $business_id] AS repos
RETURN repos
""".strip()
        return await self._store.execute_query(cypher, {"business_id": business_id})

    async def collect_graph_stats(self, repositories: list[str]) -> QueryResultWrapper:
        cypher = f"""
// {_Q_STATS}
MATCH (c:Class) WHERE c.repository IN ${_GRAPH_REPOS_PARAM}
WITH count(c) AS class_count
MATCH (m:Module) WHERE m.repository IN ${_GRAPH_REPOS_PARAM}
WITH class_count, count(m) AS module_count
OPTIONAL MATCH (a)-[r:CALLS]->(b)
WHERE (a:Class OR a:Function) AND (b:Class OR b:Function)
  AND a.repository IN ${_GRAPH_REPOS_PARAM} AND b.repository IN ${_GRAPH_REPOS_PARAM}
WITH class_count, module_count, count(r) AS calls_same_repo
OPTIONAL MATCH (x:Module)-[i:IMPORTS]->(y:Module)
WHERE x.repository IN ${_GRAPH_REPOS_PARAM} AND y.repository IN ${_GRAPH_REPOS_PARAM}
RETURN class_count, module_count, calls_same_repo, count(i) AS imports_same_repo
""".strip()
        return await self._store.execute_query(cypher, {_GRAPH_REPOS_PARAM: repositories})

    async def find_isolated_entities(self, repositories: list[str]) -> QueryResultWrapper:
        cypher = f"""
// {_Q_ISOLATED}
MATCH (n:Class)
WHERE n.repository IN ${_GRAPH_REPOS_PARAM}
  AND NOT (n)-[:CALLS|INHERITS|IMPORTS|CONTAINS]-()
RETURN n.name AS name, coalesce(n.fqn, '') AS fqn
""".strip()
        return await self._store.execute_query(cypher, {_GRAPH_REPOS_PARAM: repositories})

    async def find_circular_dependencies(self, repositories: list[str]) -> QueryResultWrapper:
        cypher = f"""
// {_Q_CYCLES}
MATCH p = (a:Module)-[:IMPORTS*2..5]->(a)
WHERE a.repository IN ${_GRAPH_REPOS_PARAM}
WITH nodes(p) AS ns
RETURN [x IN ns | coalesce(x.name, x.path, '')] AS module_path
LIMIT 50
""".strip()
        return await self._store.execute_query(cypher, {_GRAPH_REPOS_PARAM: repositories})

    async def find_cross_layer_violations(self, repositories: list[str]) -> QueryResultWrapper:
        cypher = f"""
// {_Q_CROSS_LAYER}
MATCH (ctrl:Class)-[:CALLS]->(repo:Class)
WHERE ctrl.repository IN ${_GRAPH_REPOS_PARAM}
  AND repo.repository IN ${_GRAPH_REPOS_PARAM}
  AND 'http_controller' IN coalesce(ctrl.semantic_roles, [])
  AND 'repository' IN coalesce(repo.semantic_roles, [])
RETURN ctrl.name AS ctrl_name, repo.name AS repo_name,
       coalesce(ctrl.fqn, '') AS ctrl_fqn, coalesce(repo.fqn, '') AS repo_fqn
""".strip()
        return await self._store.execute_query(cypher, {_GRAPH_REPOS_PARAM: repositories})

    async def compute_module_cohesion_insights(self, repositories: list[str]) -> QueryResultWrapper:
        cypher = f"""
// {_Q_COHESION}
MATCH (m:Module) WHERE m.repository IN ${_GRAPH_REPOS_PARAM}
MATCH (m)-[:CONTAINS]->(c1:Class)
MATCH (m)-[:CONTAINS]->(c2:Class)
WHERE id(c1) <> id(c2) AND (c1)-[:CALLS]->(c2)
WITH m, count(*) AS internal_calls
MATCH (m)-[:CONTAINS]->(all:Class)
WITH m, internal_calls, count(DISTINCT all) AS class_count
WHERE class_count > 1
WITH m, internal_calls, class_count,
  toFloat(internal_calls) / toFloat(class_count * (class_count - 1)) AS cohesion
WHERE cohesion < 0.15
RETURN coalesce(m.name, '') AS module_name, coalesce(m.path, '') AS module_path,
       internal_calls, class_count, cohesion
""".strip()
        return await self._store.execute_query(cypher, {_GRAPH_REPOS_PARAM: repositories})

    async def find_bridge_nodes(self, repositories: list[str]) -> QueryResultWrapper:
        cypher = f"""
// {_Q_BRIDGE}
MATCH (c:Class)
WHERE c.repository IN ${_GRAPH_REPOS_PARAM}
MATCH (c)-[:CALLS|INHERITS]-(other:Class)
WHERE other.repository IN ${_GRAPH_REPOS_PARAM} AND other.architecture_layer IS NOT NULL
WITH c, collect(DISTINCT other.architecture_layer) AS layers
WHERE size(layers) >= 3
RETURN c.name AS name, coalesce(c.fqn, '') AS fqn, layers
""".strip()
        return await self._store.execute_query(cypher, {_GRAPH_REPOS_PARAM: repositories})

    # ─── analysis_service ─────────────────────────────────────────────────────

    async def analyze_impact_callers(self, depth_cap: int, names: list[str]) -> QueryResultWrapper:
        cypher = (
            f"MATCH p=(target:Function)<-[:CALLS*1..{depth_cap}]-(caller:Function) "
            "WHERE target.name IN $names "
            "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(caller) "
            "RETURN "
            "caller.uid AS caller_uid, "
            "caller.name AS caller_name, "
            "caller.file AS caller_file, "
            "caller.fqn AS caller_fqn, "
            "caller.semantic_roles AS caller_semantic_roles, "
            "caller.architecture_layer AS caller_architecture_layer, "
            "pc.name AS parent_class_name, "
            "pc.semantic_roles AS parent_class_semantic_roles, "
            "length(p) AS depth, "
            "target.name AS target_name "
            "ORDER BY depth "
            "LIMIT 2000"
        )
        return await self._store.execute_query(cypher, {"names": names})

    async def verify_consistency_file_paths(self, repository: str | None) -> QueryResultWrapper:
        if repository:
            cypher = (
                "MATCH (n) WHERE n.file IS NOT NULL AND n.repository = $repo "
                "RETURN DISTINCT n.file AS file_path"
            )
            params: dict[str, Any] = {"repo": repository}
        else:
            cypher = "MATCH (n) WHERE n.file IS NOT NULL RETURN DISTINCT n.file AS file_path"
            params = {}
        return await self._store.execute_query(cypher, params)

    async def verify_consistency_stale_paths(self, repository: str | None) -> QueryResultWrapper:
        if repository:
            cypher = (
                "MATCH (n) WHERE n.file IS NOT NULL AND n.last_indexed_at IS NOT NULL "
                "AND n.repository = $repo "
                "RETURN DISTINCT n.file AS file_path, n.last_indexed_at AS last_indexed_at"
            )
            params: dict[str, Any] = {"repo": repository}
        else:
            cypher = (
                "MATCH (n) WHERE n.file IS NOT NULL AND n.last_indexed_at IS NOT NULL "
                "RETURN DISTINCT n.file AS file_path, n.last_indexed_at AS last_indexed_at"
            )
            params = {}
        return await self._store.execute_query(cypher, params)

    # ─── endpoint_queries ───────────────────────────────────────────────────────

    async def query_http_endpoints(self, repository: str) -> QueryResultWrapper:
        repo_filter = "AND f.repository = $repo " if repository else ""
        params: dict[str, Any] = {"repo": repository} if repository else {}
        http_q = (
            "MATCH (f:Function) WHERE f.api_path IS NOT NULL "
            f"{repo_filter}"
            "OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) "
            "RETURN f.name AS name, f.api_path AS path, f.http_method AS method, "
            "f.file AS file, c.name AS class_name, c.architecture_layer AS layer "
            "ORDER BY f.api_path"
        )
        return await self._store.execute_query(http_q, params)

    async def query_rpc_endpoints(self, repository: str) -> QueryResultWrapper:
        cls_repo_filter = "AND c.repository = $repo " if repository else ""
        params: dict[str, Any] = {"repo": repository} if repository else {}
        rpc_q = (
            "MATCH (c:Class) WHERE c.rpc_interface IS NOT NULL "
            f"{cls_repo_filter}"
            "OPTIONAL MATCH (c)-[:CONTAINS]->(f:Function) "
            "RETURN c.name AS class_name, c.rpc_interface AS interface, "
            "f.name AS method_name, c.architecture_layer AS layer"
        )
        return await self._store.execute_query(rpc_q, params)

    async def query_kafka_endpoints(self, repository: str) -> QueryResultWrapper:
        repo_filter = "AND f.repository = $repo " if repository else ""
        params: dict[str, Any] = {"repo": repository} if repository else {}
        kafka_q = (
            "MATCH (f:Function) WHERE f.kafka_topic IS NOT NULL "
            f"{repo_filter}"
            "RETURN f.name AS name, f.kafka_topic AS topic, f.file AS file"
        )
        return await self._store.execute_query(kafka_q, params)

    async def query_architecture_layer_counts(self, repository: str) -> QueryResultWrapper:
        repo_filter = (
            "WHERE c.architecture_layer IS NOT NULL AND c.repository = $repo"
            if repository
            else "WHERE c.architecture_layer IS NOT NULL"
        )
        params: dict[str, Any] = {"repo": repository} if repository else {}
        q = (
            f"MATCH (c:Class) {repo_filter} "
            "RETURN c.architecture_layer AS layer, count(c) AS count "
            "ORDER BY count DESC"
        )
        return await self._store.execute_query(q, params)

    # ─── agent_workflow ───────────────────────────────────────────────────────

    async def agent_find_changed_entities(self, file_path: str, repository: str | None) -> QueryResultWrapper:
        repo_filter = "AND n.repository = $repo " if repository else ""
        params: dict[str, Any] = {"file_suffix": file_path}
        if repository:
            params["repo"] = repository
        q = (
            "MATCH (n) "
            "WHERE (n:Function OR n:Class) AND n.file ENDS WITH $file_suffix "
            + repo_filter
            + "RETURN n.uid AS uid, n.name AS name, n.file AS file, "
            "n.start_line AS start_line, n.end_line AS end_line, "
            "labels(n)[0] AS entity_type, "
            "n.semantic_roles AS semantic_roles, "
            "n.architecture_layer AS architecture_layer, "
            "n.signature AS signature"
        )
        return await self._store.execute_query(q, params)

    async def agent_batch_impact_analysis(self, func_names: list[str], depth_cap: int) -> QueryResultWrapper:
        cypher = (
            f"MATCH p=(target:Function)<-[:CALLS*1..{depth_cap}]-(caller:Function) "
            "WHERE target.name IN $names "
            "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(caller) "
            "RETURN "
            "target.name AS target_name, "
            "caller.uid AS caller_uid, "
            "caller.name AS caller_name, "
            "caller.file AS caller_file, "
            "caller.semantic_roles AS caller_semantic_roles, "
            "caller.architecture_layer AS caller_architecture_layer, "
            "pc.name AS parent_class_name, "
            "pc.semantic_roles AS parent_class_semantic_roles, "
            "length(p) AS depth "
            "ORDER BY depth LIMIT 1000"
        )
        return await self._store.execute_query(cypher, {"names": func_names})

    async def agent_cross_repo_impact_by_names(self, func_names: list[str]) -> QueryResultWrapper:
        return await self._store.execute_query(
            "MATCH (f:Function)-[r:CROSS_REPO_CALLS]->(c:Class) "
            "WHERE f.name IN $names "
            "RETURN f.name AS consumer_name, f.repository AS source_repo, "
            "c.name AS provider_name, c.repository AS target_repo, "
            "r.interface AS interface",
            {"names": func_names},
        )

    async def agent_find_target_entity(self, label: str, name: str, repository: str | None) -> QueryResultWrapper:
        repo_filter = "AND n.repository = $repo " if repository else ""
        params: dict[str, Any] = {"name": name}
        if repository:
            params["repo"] = repository
        q = (
            f"MATCH (n:{label}) "
            f"WHERE (n.name = $name OR n.fqn ENDS WITH $name) {repo_filter}"
            "RETURN n.uid AS uid, n.name AS name, n.file AS file, "
            "n.start_line AS start_line, n.end_line AS end_line, "
            "n.signature AS signature, n.code_snippet AS code_snippet, "
            "n.docstring AS docstring, n.fqn AS fqn, "
            "n.semantic_roles AS semantic_roles, "
            "n.architecture_layer AS architecture_layer, "
            "n.repository AS repository, "
            "n.annotations AS annotations "
            "LIMIT 1"
        )
        return await self._store.execute_query(q, params)

    async def agent_get_callers(self, label: str, uid: str, limit: int) -> QueryResultWrapper:
        q = (
            f"MATCH (caller:Function)-[:CALLS]->(target:{label} {{uid: $uid}}) "
            "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(caller) "
            "RETURN caller.uid AS uid, caller.name AS name, caller.file AS file, "
            "caller.signature AS signature, caller.architecture_layer AS layer, "
            "pc.name AS parent_class "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_get_callees_function(self, uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (source:Function {uid: $uid})-[:CALLS]->(callee:Function) "
            "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(callee) "
            "RETURN callee.uid AS uid, callee.name AS name, callee.file AS file, "
            "callee.signature AS signature, callee.architecture_layer AS layer, "
            "pc.name AS parent_class "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_get_callees_class(self, uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (cls:Class {uid: $uid})-[:CONTAINS]->(m:Function)-[:CALLS]->(callee:Function) "
            "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(callee) "
            "RETURN DISTINCT callee.uid AS uid, callee.name AS name, callee.file AS file, "
            "callee.signature AS signature, callee.architecture_layer AS layer, "
            "pc.name AS parent_class "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_class_methods_only(self, uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class {uid: $uid})-[:CONTAINS]->(m:Function) "
            "RETURN m.uid AS uid, m.name AS name, m.signature AS signature, "
            "m.architecture_layer AS layer "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_parent_of_function(self, uid: str) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class)-[:CONTAINS]->(f:Function {uid: $uid}) "
            "RETURN c.uid AS uid, c.name AS name, c.file AS file, "
            "c.fqn AS fqn, c.signature AS signature, "
            "c.semantic_roles AS semantic_roles, "
            "c.architecture_layer AS architecture_layer, "
            "c.base_classes AS base_classes "
            "LIMIT 1"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_sibling_methods(self, cls_uid: str, func_uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class {uid: $cls_uid})-[:CONTAINS]->(m:Function) "
            "WHERE m.uid <> $func_uid "
            "RETURN m.uid AS uid, m.name AS name, m.signature AS signature, "
            "m.architecture_layer AS layer "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"cls_uid": cls_uid, "func_uid": func_uid})

    async def agent_cross_repo_from_function(self, uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function {uid: $uid})-[r:CROSS_REPO_CALLS]->(c:Class) "
            "RETURN c.uid AS uid, c.name AS name, c.repository AS repository, "
            "c.fqn AS fqn, r.interface AS interface, r.target_repo AS target_repo "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_cross_repo_to_class(self, uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function)-[r:CROSS_REPO_CALLS]->(c:Class {uid: $uid}) "
            "RETURN f.uid AS uid, f.name AS name, f.repository AS repository, "
            "f.fqn AS fqn, r.interface AS interface, r.source_repo AS source_repo "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_rpc_interface_contracts(self, class_uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class {uid: $uid})-[:IMPLEMENTS]->(iface:Class) "
            "WHERE coalesce(iface.is_rpc_contract, false) = true "
            "RETURN iface.uid AS uid, iface.name AS name, iface.fqn AS fqn, "
            "iface.contract_methods AS contract_methods "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": class_uid})

    async def agent_class_function_uids(self, uid: str) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class {uid: $uid})-[:CONTAINS]->(f:Function) "
            "RETURN f.uid AS uid LIMIT 200"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def agent_event_consumes(self, uids: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function)-[:EVENT_CONSUMES]->(m:Module) "
            "WHERE f.uid IN $uids "
            "RETURN DISTINCT coalesce(m.kafka_topic, m.name) AS topic"
        )
        return await self._store.execute_query(q, {"uids": uids})

    async def agent_event_produces(self, uids: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function)-[:EVENT_PRODUCES]->(m:Module) "
            "WHERE f.uid IN $uids "
            "RETURN DISTINCT coalesce(m.kafka_topic, m.name) AS topic"
        )
        return await self._store.execute_query(q, {"uids": uids})

    async def agent_entity_tables(self, class_uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (dao:Class {uid: $uid})-[r:ACCESSES_TABLE]->(entity:Class) "
            "RETURN entity.uid AS uid, entity.name AS name, entity.fqn AS fqn, "
            "entity.table_name AS table_name, r.table_name AS rel_table_name "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": class_uid})

    async def agent_di_dependencies(self, class_uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (source:Class {uid: $uid})-[r:DEPENDS_ON]->(target:Class) "
            "RETURN target.uid AS uid, target.name AS name, target.fqn AS fqn, "
            "target.architecture_layer AS layer, r.injection_type AS injection_type, "
            "r.field_name AS field_name "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": class_uid})

    async def agent_related_interfaces(self, class_uid: str, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class {uid: $uid})-[:IMPLEMENTS]->(iface:Class) "
            "RETURN iface.uid AS uid, iface.name AS name, iface.fqn AS fqn "
            f"LIMIT {limit}"
        )
        return await self._store.execute_query(q, {"uid": class_uid})

    async def agent_has_test_reference(self, needle: str) -> QueryResultWrapper:
        q = (
            "MATCH (t:Function) "
            "WHERE toLower(t.file) CONTAINS 'test' "
            "AND t.code_snippet IS NOT NULL AND t.code_snippet <> '' "
            "AND t.code_snippet CONTAINS $needle "
            "RETURN t.uid AS uid LIMIT 1"
        )
        return await self._store.execute_query(q, {"needle": needle})

    async def agent_quality_score_lookup(self, uid: str, type_clause: str) -> QueryResultWrapper:
        q = (
            f"MATCH (n {{uid: $uid}}) WHERE {type_clause} "
            "RETURN labels(n)[0] AS label, n.name AS name, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.code_snippet, '') AS code_snippet, "
            "coalesce(n.docstring, '') AS docstring, "
            "n.semantic_roles AS semantic_roles"
        )
        return await self._store.execute_query(q, {"uid": uid})
