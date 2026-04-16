"""P2 Cross-repo enrichment: RPC resolution, Spring DI graph, Entity-table mapping.

Runs as a global post-indexing pass across all repositories.  Each enrichment
is idempotent — old edges are deleted before recreation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from log import get_logger

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


def _parse_annotation_arg(annotation: str) -> str:
    """Extract first string argument from an annotation like @Table(name="users")."""
    s = annotation.strip()
    start = s.find("(")
    if start == -1:
        return ""
    depth = 0
    end = -1
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return ""
    inner = s[start + 1 : end]
    m = re.search(r'["\']((?:[^"\'\\]|\\.)*)["\']', inner)
    if m:
        return m.group(1)
    m2 = re.search(r'=\s*["\']((?:[^"\'\\]|\\.)*)["\']', inner)
    if m2:
        return m2.group(1)
    return ""


def _annotation_simple_name(raw: str) -> str:
    s = raw.strip()
    if s.startswith("@"):
        s = s[1:]
    paren = s.find("(")
    if paren != -1:
        s = s[:paren]
    return s.rsplit(".", 1)[-1].strip()


_RPC_PROVIDER_NAMES = frozenset({"MoaProvider", "DubboService"})
_RPC_CONSUMER_NAMES = frozenset({"MoaConsumer", "DubboReference"})
_DI_INJECT_NAMES = frozenset({"Autowired", "Inject", "Resource"})
_ENTITY_ANNOTATION_NAMES = frozenset({"Entity", "Table", "Document", "MappedSuperclass"})


class CrossRepoEnricher:
    """Global enrichment pass that resolves cross-repository relationships."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def enrich_all(self) -> dict[str, Any]:
        """Run all cross-repo enrichment passes. Returns counts."""
        rpc_count = await self._enrich_cross_repo_rpc()
        di_count = await self._enrich_di_graph()
        entity_count = await self._enrich_entity_mapping()
        return {
            "cross_repo_rpc_edges": rpc_count,
            "di_dependency_edges": di_count,
            "entity_table_edges": entity_count,
        }

    # ─── P2-1: Cross-Repository RPC Resolution ─────────────────────────

    async def _enrich_cross_repo_rpc(self) -> int:
        """Match @MoaConsumer/@DubboReference → @MoaProvider/@DubboService across repos."""
        count = 0
        try:
            await self._store.execute_query(
                "MATCH ()-[r:CROSS_REPO_CALLS]->() DELETE r"
            )

            providers = await self._store.execute_query(
                "MATCH (c:Class) "
                "WHERE c.semantic_roles IS NOT NULL AND 'rpc_provider' IN c.semantic_roles "
                "RETURN c.uid AS uid, c.name AS name, c.rpc_interface AS rpc_interface, "
                "c.repository AS repository, c.annotations AS annotations, c.fqn AS fqn"
            )

            iface_to_provider: dict[str, dict[str, Any]] = {}
            for row in providers.data:
                uid = row.get("uid") or ""
                repo = row.get("repository") or ""
                rpc_iface = row.get("rpc_interface") or ""
                fqn = row.get("fqn") or ""
                name = row.get("name") or ""
                annotations = row.get("annotations") or []

                iface_key = rpc_iface or ""
                if not iface_key and isinstance(annotations, list):
                    for raw in annotations:
                        simple = _annotation_simple_name(raw)
                        if simple in _RPC_PROVIDER_NAMES:
                            iface_key = _parse_annotation_arg(raw)
                            if iface_key:
                                break

                if not iface_key:
                    iface_key = name

                if iface_key:
                    iface_to_provider[iface_key] = {
                        "uid": uid,
                        "repository": repo,
                        "fqn": fqn,
                        "name": name,
                    }

            consumers = await self._store.execute_query(
                "MATCH (f:Function) "
                "WHERE f.semantic_roles IS NOT NULL AND 'rpc_consumer' IN f.semantic_roles "
                "OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) "
                "RETURN f.uid AS uid, f.name AS name, f.annotations AS annotations, "
                "f.repository AS repository, c.uid AS class_uid, c.name AS class_name, "
                "c.repository AS class_repository"
            )

            for row in consumers.data:
                func_uid = row.get("uid") or ""
                func_annotations = row.get("annotations") or []
                consumer_repo = row.get("repository") or row.get("class_repository") or ""

                if not isinstance(func_annotations, list):
                    func_annotations = []

                target_iface = ""
                for raw in func_annotations:
                    simple = _annotation_simple_name(raw)
                    if simple in _RPC_CONSUMER_NAMES:
                        target_iface = _parse_annotation_arg(raw)
                        if target_iface:
                            break

                if not target_iface:
                    continue

                provider = iface_to_provider.get(target_iface)
                if not provider:
                    for key, prov in iface_to_provider.items():
                        if key.endswith(f".{target_iface}") or target_iface.endswith(f".{key}"):
                            provider = prov
                            break

                if not provider:
                    continue

                if consumer_repo == provider["repository"]:
                    continue

                try:
                    await self._store.execute_query(
                        "MATCH (consumer:Function {uid: $consumer_uid}), "
                        "(provider:Class {uid: $provider_uid}) "
                        "MERGE (consumer)-[r:CROSS_REPO_CALLS]->(provider) "
                        "SET r.source_repo = $source_repo, "
                        "r.target_repo = $target_repo, "
                        "r.interface = $interface",
                        {
                            "consumer_uid": func_uid,
                            "provider_uid": provider["uid"],
                            "source_repo": consumer_repo,
                            "target_repo": provider["repository"],
                            "interface": target_iface,
                        },
                    )
                    count += 1
                except Exception as exc:
                    log.warning("cross_repo_rpc_edge_failed",
                                consumer=func_uid, provider=provider["uid"], error=str(exc))

        except Exception as exc:
            log.error("cross_repo_rpc_enrichment_failed", error=str(exc))
        log.info("cross_repo_rpc_enrichment_done", edges_created=count)
        return count

    # ─── P2-5: Spring DI Container Graph ────────────────────────────────

    async def _enrich_di_graph(self) -> int:
        """Build DEPENDS_ON edges from @Autowired/@Inject/@Resource annotations."""
        count = 0
        try:
            await self._store.execute_query(
                "MATCH ()-[r:DEPENDS_ON]->() DELETE r"
            )

            classes_with_di = await self._store.execute_query(
                "MATCH (c:Class) "
                "WHERE c.annotations IS NOT NULL "
                "RETURN c.uid AS uid, c.name AS name, c.annotations AS annotations, "
                "c.repository AS repository"
            )

            for row in classes_with_di.data:
                cls_uid = row.get("uid") or ""
                annotations = row.get("annotations") or []
                repository = row.get("repository") or ""
                if not isinstance(annotations, list):
                    continue

                has_di = False
                for raw in annotations:
                    simple = _annotation_simple_name(raw)
                    if simple in _DI_INJECT_NAMES:
                        has_di = True
                        break
                if has_di:
                    pass

            fields_with_inject = await self._store.execute_query(
                "MATCH (c:Class)-[:CONTAINS]->(f:Function) "
                "WHERE f.annotations IS NOT NULL "
                "RETURN c.uid AS class_uid, c.name AS class_name, c.repository AS repository, "
                "f.uid AS func_uid, f.name AS func_name, f.annotations AS annotations, "
                "f.signature AS signature"
            )

            all_classes = await self._store.execute_query(
                "MATCH (c:Class) RETURN c.uid AS uid, c.name AS name, c.fqn AS fqn, "
                "c.repository AS repository"
            )
            class_name_to_uid: dict[str, str] = {}
            for row in all_classes.data:
                name = row.get("name") or ""
                fqn = row.get("fqn") or ""
                uid = row.get("uid") or ""
                if name:
                    class_name_to_uid[name] = uid
                if fqn:
                    class_name_to_uid[fqn] = uid
                    simple = fqn.rsplit(".", 1)[-1]
                    if simple and simple not in class_name_to_uid:
                        class_name_to_uid[simple] = uid

            for row in fields_with_inject.data:
                cls_uid = row.get("class_uid") or ""
                func_annotations = row.get("annotations") or []
                func_name = row.get("func_name") or ""
                signature = row.get("signature") or ""

                if not isinstance(func_annotations, list):
                    continue

                injection_type = ""
                for raw in func_annotations:
                    simple = _annotation_simple_name(raw)
                    if simple in _DI_INJECT_NAMES:
                        if func_name and (func_name.startswith("<init>")
                                          or func_name == "__init__"
                                          or "constructor" in func_name.lower()):
                            injection_type = "constructor"
                        elif func_name and func_name.startswith("set"):
                            injection_type = "setter"
                        else:
                            injection_type = "field"
                        break

                if not injection_type:
                    continue

                target_types = self._extract_type_names_from_signature(signature, func_name)
                for type_name in target_types:
                    target_uid = class_name_to_uid.get(type_name)
                    if not target_uid or target_uid == cls_uid:
                        continue
                    try:
                        await self._store.execute_query(
                            "MATCH (source:Class {uid: $source_uid}), "
                            "(target:Class {uid: $target_uid}) "
                            "MERGE (source)-[r:DEPENDS_ON]->(target) "
                            "SET r.injection_type = $injection_type, "
                            "r.field_name = $field_name",
                            {
                                "source_uid": cls_uid,
                                "target_uid": target_uid,
                                "injection_type": injection_type,
                                "field_name": func_name,
                            },
                        )
                        count += 1
                    except Exception as exc:
                        log.warning("di_edge_failed",
                                    source=cls_uid, target=target_uid, error=str(exc))

        except Exception as exc:
            log.error("di_graph_enrichment_failed", error=str(exc))
        log.info("di_graph_enrichment_done", edges_created=count)
        return count

    @staticmethod
    def _extract_type_names_from_signature(signature: str, func_name: str) -> list[str]:
        """Best-effort extraction of type names from a Java method/field signature."""
        types: list[str] = []
        if not signature:
            return types
        paren_start = signature.find("(")
        paren_end = signature.rfind(")")
        if paren_start != -1 and paren_end != -1:
            params_str = signature[paren_start + 1 : paren_end]
            for param in params_str.split(","):
                param = param.strip()
                if not param:
                    continue
                parts = param.split()
                for part in parts:
                    cleaned = part.strip()
                    cleaned = re.sub(r"<.*>", "", cleaned)
                    cleaned = cleaned.rstrip("[]")
                    if cleaned and cleaned[0].isupper() and cleaned not in (
                        "String", "Integer", "Long", "Boolean", "Double", "Float",
                        "List", "Map", "Set", "Collection", "Optional", "Object",
                        "Void", "Class", "Enum",
                    ):
                        types.append(cleaned)
        else:
            parts = signature.split()
            for part in parts:
                cleaned = part.strip()
                cleaned = re.sub(r"<.*>", "", cleaned)
                cleaned = cleaned.rstrip("[]")
                if cleaned and cleaned[0].isupper() and cleaned not in (
                    "String", "Integer", "Long", "Boolean", "Double", "Float",
                    "List", "Map", "Set", "Collection", "Optional", "Object",
                    "Void", "Class", "Enum", "private", "public", "protected",
                    "static", "final", "abstract", "void",
                ):
                    types.append(cleaned)
        return types

    # ─── P2-4: Database Entity Mapping ──────────────────────────────────

    async def _enrich_entity_mapping(self) -> int:
        """Create ACCESSES_TABLE edges from Repository/DAO classes to Entity classes."""
        count = 0
        try:
            await self._store.execute_query(
                "MATCH ()-[r:ACCESSES_TABLE]->() DELETE r"
            )

            entity_classes = await self._store.execute_query(
                "MATCH (c:Class) "
                "WHERE c.semantic_roles IS NOT NULL AND 'entity' IN c.semantic_roles "
                "RETURN c.uid AS uid, c.name AS name, c.fqn AS fqn, "
                "c.annotations AS annotations, c.repository AS repository"
            )

            entity_map: dict[str, dict[str, Any]] = {}
            for row in entity_classes.data:
                uid = row.get("uid") or ""
                name = row.get("name") or ""
                fqn = row.get("fqn") or ""
                annotations = row.get("annotations") or []

                table_name = ""
                if isinstance(annotations, list):
                    for raw in annotations:
                        simple = _annotation_simple_name(raw)
                        if simple == "Table":
                            table_name = _parse_annotation_arg(raw)
                            if table_name:
                                break

                if table_name:
                    try:
                        await self._store.execute_query(
                            "MATCH (c:Class {uid: $uid}) SET c.table_name = $table_name",
                            {"uid": uid, "table_name": table_name},
                        )
                    except Exception as exc:
                        log.warning("entity_table_name_set_failed", uid=uid, error=str(exc))

                if name:
                    entity_map[name] = {"uid": uid, "table_name": table_name}
                if fqn:
                    entity_map[fqn] = {"uid": uid, "table_name": table_name}
                    simple_name = fqn.rsplit(".", 1)[-1]
                    if simple_name and simple_name not in entity_map:
                        entity_map[simple_name] = {"uid": uid, "table_name": table_name}

            dao_classes = await self._store.execute_query(
                "MATCH (c:Class) "
                "WHERE c.semantic_roles IS NOT NULL "
                "AND ('repository' IN c.semantic_roles OR c.architecture_layer = 'data_access') "
                "RETURN c.uid AS uid, c.name AS name, c.fqn AS fqn, "
                "c.base_classes AS base_classes, c.repository AS repository"
            )

            for row in dao_classes.data:
                dao_uid = row.get("uid") or ""
                dao_name = row.get("name") or ""
                base_classes = row.get("base_classes") or []

                if not isinstance(base_classes, list):
                    base_classes = []

                linked_entities: set[str] = set()

                for base in base_classes:
                    if not isinstance(base, str):
                        continue
                    generic_match = re.search(r"<\s*(\w+)", base)
                    if generic_match:
                        type_param = generic_match.group(1)
                        entity = entity_map.get(type_param)
                        if entity and entity["uid"] not in linked_entities:
                            linked_entities.add(entity["uid"])
                            try:
                                await self._store.execute_query(
                                    "MATCH (dao:Class {uid: $dao_uid}), "
                                    "(entity:Class {uid: $entity_uid}) "
                                    "MERGE (dao)-[r:ACCESSES_TABLE]->(entity) "
                                    "SET r.table_name = $table_name",
                                    {
                                        "dao_uid": dao_uid,
                                        "entity_uid": entity["uid"],
                                        "table_name": entity.get("table_name") or "",
                                    },
                                )
                                count += 1
                            except Exception as exc:
                                log.warning("entity_mapping_edge_failed",
                                            dao=dao_uid, entity=entity["uid"],
                                            error=str(exc))

                if not linked_entities:
                    for entity_name, entity_info in entity_map.items():
                        if (entity_name in dao_name
                                and entity_info["uid"] not in linked_entities):
                            linked_entities.add(entity_info["uid"])
                            try:
                                await self._store.execute_query(
                                    "MATCH (dao:Class {uid: $dao_uid}), "
                                    "(entity:Class {uid: $entity_uid}) "
                                    "MERGE (dao)-[r:ACCESSES_TABLE]->(entity) "
                                    "SET r.table_name = $table_name",
                                    {
                                        "dao_uid": dao_uid,
                                        "entity_uid": entity_info["uid"],
                                        "table_name": entity_info.get("table_name") or "",
                                    },
                                )
                                count += 1
                            except Exception as exc:
                                log.warning("entity_mapping_edge_failed",
                                            dao=dao_uid, entity=entity_info["uid"],
                                            error=str(exc))

        except Exception as exc:
            log.error("entity_mapping_enrichment_failed", error=str(exc))
        log.info("entity_mapping_enrichment_done", edges_created=count)
        return count
