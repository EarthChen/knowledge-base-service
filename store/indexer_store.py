"""Indexer-related graph queries: entry-point discovery, enrichment, cross-repo."""

from __future__ import annotations

from store.falkordb_store import FalkorDBStore, QueryResultWrapper


class IndexerStore:
    """Indexer-related graph queries: entry points, enrichment, cross-repo."""

    def __init__(self, base_store: FalkorDBStore) -> None:
        self._store = base_store

    # --- indexer/business_flow_inferencer.py ---
    async def entry_points_semantic_functions(self) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function) "
            "WHERE f.semantic_roles IS NOT NULL AND "
            "ANY(r IN f.semantic_roles WHERE r IN "
            "['http_endpoint', 'rpc_consumer', 'message_listener', 'scheduled_task']) "
            "RETURN f"
        )
        return await self._store.execute_query(q)

    async def entry_points_semantic_controller_classes(self) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class)-[:CONTAINS]->(f:Function) "
            "WHERE c.semantic_roles IS NOT NULL AND "
            "ANY(r IN c.semantic_roles WHERE r IN "
            "['http_controller', 'rpc_provider']) "
            "RETURN f"
        )
        return await self._store.execute_query(q)

    async def entry_points_legacy_signatures(self) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function) "
            "WHERE f.signature CONTAINS '@RequestMapping' "
            "OR f.signature CONTAINS '@GetMapping' "
            "OR f.signature CONTAINS '@PostMapping' "
            "OR f.signature CONTAINS '@PutMapping' "
            "OR f.signature CONTAINS '@DeleteMapping' "
            "OR f.signature CONTAINS '@MoaProvider' "
            "OR f.signature CONTAINS '@KafkaListener' "
            "OR f.signature CONTAINS '@KafkaHandler' "
            "OR f.signature CONTAINS '@app.route' "
            "OR f.signature CONTAINS '@Scheduled' "
            "RETURN f"
        )
        return await self._store.execute_query(q)

    async def entry_points_weak_leaf_functions(self) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function)-[:CALLS]->() "
            "WHERE NOT ()-[:CALLS]->(f) "
            "RETURN DISTINCT f"
        )
        return await self._store.execute_query(q)

    # --- indexer/graph_enricher.py (reads) ---
    async def enrich_scan_http_endpoint_rows(self) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function) "
            "WHERE f.semantic_roles IS NOT NULL AND 'http_endpoint' IN f.semantic_roles "
            "OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) "
            "RETURN f.uid AS uid, f.annotations AS f_ann, c.annotations AS c_ann"
        )
        return await self._store.execute_query(q)

    async def enrich_set_function_http_props(self, uid: str, method: str, path: str) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function) WHERE f.uid = $uid "
            "SET f.http_method = $method, f.api_path = $path"
        )
        return await self._store.execute_query(q, {"uid": uid, "method": method, "path": path})

    async def enrich_scan_rpc_provider_classes(self) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class) "
            "WHERE c.semantic_roles IS NOT NULL AND 'rpc_provider' IN c.semantic_roles "
            "RETURN c.uid AS uid, c.annotations AS annotations"
        )
        return await self._store.execute_query(q)

    async def enrich_set_class_rpc_interface(self, uid: str, iface: str) -> QueryResultWrapper:
        q = "MATCH (c:Class) WHERE c.uid = $uid SET c.rpc_interface = $iface"
        return await self._store.execute_query(q, {"uid": uid, "iface": iface})

    async def enrich_scan_kafka_listener_functions(self) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function) "
            "WHERE f.semantic_roles IS NOT NULL AND 'message_listener' IN f.semantic_roles "
            "RETURN f.uid AS uid, f.annotations AS annotations"
        )
        return await self._store.execute_query(q)

    async def enrich_set_function_kafka_topic(self, uid: str, topic: str) -> QueryResultWrapper:
        q = "MATCH (f:Function) WHERE f.uid = $uid SET f.kafka_topic = $topic"
        return await self._store.execute_query(q, {"uid": uid, "topic": topic})

    async def enrich_list_classes_with_semantic_roles(self) -> QueryResultWrapper:
        q = "MATCH (c:Class) RETURN c.uid AS uid, c.semantic_roles AS sr, c.fqn AS fqn"
        return await self._store.execute_query(q)

    async def enrich_set_class_layer_and_functions(self, uid: str, layer: str) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class) WHERE c.uid = $uid "
            "SET c.architecture_layer = $layer "
            "WITH c "
            "MATCH (c)-[:CONTAINS]->(f:Function) "
            "SET f.architecture_layer = $layer "
            "RETURN count(f) AS fn"
        )
        return await self._store.execute_query(q, {"uid": uid, "layer": layer})

    async def enrich_reset_rpc_contract_flags(self) -> QueryResultWrapper:
        q = (
            "MATCH (iface:Class) WHERE coalesce(iface.is_interface, false) = true "
            "SET iface.is_rpc_contract = false, iface.contract_methods = []"
        )
        return await self._store.execute_query(q)

    async def enrich_rpc_provider_interface_candidates(self) -> QueryResultWrapper:
        q = (
            "MATCH (iface:Class) WHERE coalesce(iface.is_interface, false) = true "
            "MATCH (p:Class)-[:IMPLEMENTS]->(iface) "
            "WHERE p.semantic_roles IS NOT NULL AND 'rpc_provider' IN p.semantic_roles "
            "RETURN DISTINCT iface.uid AS uid"
        )
        return await self._store.execute_query(q)

    async def enrich_iface_contract_methods(self, uid: str) -> QueryResultWrapper:
        q = (
            "MATCH (iface:Class {uid: $uid})-[:CONTAINS]->(m:Function) "
            "RETURN m.name AS name, m.signature AS signature ORDER BY m.name"
        )
        return await self._store.execute_query(q, {"uid": uid})

    async def enrich_set_iface_rpc_contract(self, uid: str, methods: list[str]) -> QueryResultWrapper:
        q = (
            "MATCH (iface:Class {uid: $uid}) "
            "SET iface.is_rpc_contract = true, iface.contract_methods = $methods"
        )
        return await self._store.execute_query(q, {"uid": uid, "methods": methods})

    async def enrich_delete_all_event_produces_edges(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:EVENT_PRODUCES]->() DELETE r")

    async def enrich_delete_all_event_consumes_edges(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:EVENT_CONSUMES]->() DELETE r")

    async def enrich_kafka_consumer_functions_with_topic(self) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function) "
            "WHERE f.semantic_roles IS NOT NULL AND 'message_listener' IN f.semantic_roles "
            "AND coalesce(f.kafka_topic, '') <> '' "
            "RETURN f.uid AS uid, f.kafka_topic AS topic"
        )
        return await self._store.execute_query(q)

    async def enrich_kafka_producer_call_rows(self) -> QueryResultWrapper:
        q = (
            "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
            "WHERE callee.name IN ['sendSync', 'sendAsync', 'send', 'sendDefault', 'convertAndSend', 'publish'] "
            "MATCH (owner:Class)-[:CONTAINS]->(callee) "
            "WHERE toLower(owner.name) CONTAINS 'kafka' OR toLower(owner.name) CONTAINS 'producer' "
            "RETURN DISTINCT caller.uid AS uid, caller.code_snippet AS snippet"
        )
        return await self._store.execute_query(q)

    # --- indexer/cross_repo_enricher.py ---
    async def cross_repo_delete_edges(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:CROSS_REPO_CALLS]->() DELETE r")

    async def cross_repo_rpc_providers(self) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class) "
            "WHERE c.semantic_roles IS NOT NULL AND 'rpc_provider' IN c.semantic_roles "
            "RETURN c.uid AS uid, c.name AS name, c.rpc_interface AS rpc_interface, "
            "c.repository AS repository, c.annotations AS annotations, c.fqn AS fqn"
        )
        return await self._store.execute_query(q)

    async def cross_repo_rpc_consumers(self) -> QueryResultWrapper:
        q = (
            "MATCH (f:Function) "
            "WHERE f.semantic_roles IS NOT NULL AND 'rpc_consumer' IN f.semantic_roles "
            "OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) "
            "RETURN f.uid AS uid, f.name AS name, f.annotations AS annotations, "
            "f.repository AS repository, c.uid AS class_uid, c.name AS class_name, "
            "c.repository AS class_repository"
        )
        return await self._store.execute_query(q)

    async def cross_repo_merge_rpc_edge(
        self,
        consumer_uid: str,
        provider_uid: str,
        source_repo: str,
        target_repo: str,
        interface: str,
    ) -> QueryResultWrapper:
        q = (
            "MATCH (consumer:Function {uid: $consumer_uid}), "
            "(provider:Class {uid: $provider_uid}) "
            "MERGE (consumer)-[r:CROSS_REPO_CALLS]->(provider) "
            "SET r.source_repo = $source_repo, "
            "r.target_repo = $target_repo, "
            "r.interface = $interface"
        )
        return await self._store.execute_query(
            q,
            {
                "consumer_uid": consumer_uid,
                "provider_uid": provider_uid,
                "source_repo": source_repo,
                "target_repo": target_repo,
                "interface": interface,
            },
        )

    async def di_delete_depends_on_edges(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:DEPENDS_ON]->() DELETE r")

    async def di_all_classes(self) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class) RETURN c.uid AS uid, c.name AS name, c.fqn AS fqn, "
            "c.repository AS repository"
        )
        return await self._store.execute_query(q)

    async def di_field_and_constructor_candidates(self) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class)-[:CONTAINS]->(f:Function) "
            "WHERE (f.annotations IS NOT NULL AND size(f.annotations) > 0) "
            "   OR (f.semantic_roles IS NOT NULL AND 'di_inject' IN f.semantic_roles) "
            "RETURN c.uid AS class_uid, c.name AS class_name, c.repository AS repository, "
            "f.uid AS func_uid, f.name AS func_name, f.annotations AS annotations, "
            "f.signature AS signature, f.semantic_roles AS semantic_roles, "
            "f.injection_type AS injection_type, f.field_type AS field_type"
        )
        return await self._store.execute_query(q)

    async def di_merge_depends_on(
        self,
        source_uid: str,
        target_uid: str,
        injection_type: str,
        field_name: str,
    ) -> QueryResultWrapper:
        q = (
            "MATCH (source:Class {uid: $source_uid}), "
            "(target:Class {uid: $target_uid}) "
            "MERGE (source)-[r:DEPENDS_ON]->(target) "
            "SET r.injection_type = $injection_type, "
            "r.field_name = $field_name"
        )
        return await self._store.execute_query(
            q,
            {
                "source_uid": source_uid,
                "target_uid": target_uid,
                "injection_type": injection_type,
                "field_name": field_name,
            },
        )

    async def entity_delete_accesses_table_edges(self) -> QueryResultWrapper:
        return await self._store.execute_query("MATCH ()-[r:ACCESSES_TABLE]->() DELETE r")

    async def entity_semantic_entity_classes(self) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class) "
            "WHERE c.semantic_roles IS NOT NULL AND 'entity' IN c.semantic_roles "
            "RETURN c.uid AS uid, c.name AS name, c.fqn AS fqn, "
            "c.annotations AS annotations, c.repository AS repository"
        )
        return await self._store.execute_query(q)

    async def entity_set_table_name(self, uid: str, table_name: str) -> QueryResultWrapper:
        q = "MATCH (c:Class {uid: $uid}) SET c.table_name = $table_name"
        return await self._store.execute_query(q, {"uid": uid, "table_name": table_name})

    async def entity_dao_candidates(self) -> QueryResultWrapper:
        q = (
            "MATCH (c:Class) "
            "WHERE c.semantic_roles IS NOT NULL "
            "AND ('repository' IN c.semantic_roles OR c.architecture_layer = 'data_access') "
            "RETURN c.uid AS uid, c.name AS name, c.fqn AS fqn, "
            "c.base_classes AS base_classes, c.repository AS repository"
        )
        return await self._store.execute_query(q)

    async def entity_merge_accesses_table(
        self,
        dao_uid: str,
        entity_uid: str,
        table_name: str,
    ) -> QueryResultWrapper:
        q = (
            "MATCH (dao:Class {uid: $dao_uid}), "
            "(entity:Class {uid: $entity_uid}) "
            "MERGE (dao)-[r:ACCESSES_TABLE]->(entity) "
            "SET r.table_name = $table_name"
        )
        return await self._store.execute_query(
            q,
            {"dao_uid": dao_uid, "entity_uid": entity_uid, "table_name": table_name},
        )
