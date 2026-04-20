"""P2 Cross-repo enrichment: RPC resolution, Spring DI graph, Entity-table mapping.

Runs as a global post-indexing pass across all repositories.  Each enrichment
is idempotent — old edges are deleted before recreation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from log import get_logger

from indexer.java_annotation_args import extract_java_annotation_primary_arg
from store.indexer_store import IndexerStore

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


def _parse_annotation_arg(annotation: str) -> str:
    """Extract string or ``interfaceClass = SomeIface.class`` from a Java annotation."""
    return extract_java_annotation_primary_arg(annotation)


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
_ENTITY_ANNOTATION_NAMES = frozenset({"Entity", "Table", "Document", "MappedSuperclass", "TableName"})


class CrossRepoEnricher:
    """Global enrichment pass that resolves cross-repository relationships."""

    def __init__(self, store: FalkorDBStore, indexer_store: IndexerStore | None = None) -> None:
        self._store = store
        self._idx = indexer_store or IndexerStore(store)

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
            await self._idx.cross_repo_delete_edges()

            providers = await self._idx.cross_repo_rpc_providers()

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

                provider_info = {"uid": uid, "repository": repo, "fqn": fqn, "name": name}

                if iface_key:
                    iface_to_provider[iface_key] = provider_info

                interfaces = row.get("interfaces") or []
                if isinstance(interfaces, list):
                    for iface_name in interfaces:
                        if iface_name:
                            iface_to_provider[iface_name] = provider_info

                if not iface_key and name:
                    iface_to_provider[name] = provider_info

            consumers = await self._idx.cross_repo_rpc_consumers()

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
                    simple_name = (
                        target_iface.rsplit(".", 1)[-1] if "." in target_iface else target_iface
                    )
                    if simple_name:
                        provider = iface_to_provider.get(simple_name)
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
                    await self._idx.cross_repo_merge_rpc_edge(
                        func_uid,
                        provider["uid"],
                        consumer_repo,
                        provider["repository"],
                        target_iface,
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
        """Build DEPENDS_ON edges from DI annotations and constructor injection."""
        count = 0
        try:
            await self._idx.di_delete_depends_on_edges()

            all_classes = await self._idx.di_all_classes()
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

            di_fields = await self._idx.di_field_and_constructor_candidates()

            for row in di_fields.data:
                cls_uid = row.get("class_uid") or ""
                func_annotations = row.get("annotations") or []
                func_name = row.get("func_name") or ""
                signature = row.get("signature") or ""
                semantic_roles = row.get("semantic_roles") or []
                stored_injection_type = row.get("injection_type") or ""
                field_type = row.get("field_type") or ""

                if not isinstance(func_annotations, list):
                    func_annotations = []
                if not isinstance(semantic_roles, list):
                    semantic_roles = []

                injection_type = stored_injection_type
                if not injection_type:
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

                is_di = injection_type or "di_inject" in semantic_roles
                if not is_di:
                    continue

                if not injection_type:
                    injection_type = "constructor" if func_name.startswith("field:") else "field"

                target_types: list[str] = []
                if field_type:
                    cleaned = re.sub(r"<.*>", "", field_type).strip()
                    if cleaned and cleaned[0].isupper():
                        target_types.append(cleaned)
                if not target_types:
                    target_types = self._extract_type_names_from_signature(signature, func_name)

                for type_name in target_types:
                    target_uid = class_name_to_uid.get(type_name)
                    if not target_uid or target_uid == cls_uid:
                        continue
                    try:
                        await self._idx.di_merge_depends_on(
                            cls_uid,
                            target_uid,
                            injection_type,
                            func_name,
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
            await self._idx.entity_delete_accesses_table_edges()

            entity_classes = await self._idx.entity_semantic_entity_classes()

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
                        if simple in ("Table", "TableName"):
                            table_name = _parse_annotation_arg(raw)
                            if table_name:
                                break

                if table_name:
                    try:
                        await self._idx.entity_set_table_name(uid, table_name)
                    except Exception as exc:
                        log.warning("entity_table_name_set_failed", uid=uid, error=str(exc))

                if name:
                    entity_map[name] = {"uid": uid, "table_name": table_name}
                if fqn:
                    entity_map[fqn] = {"uid": uid, "table_name": table_name}
                    simple_name = fqn.rsplit(".", 1)[-1]
                    if simple_name and simple_name not in entity_map:
                        entity_map[simple_name] = {"uid": uid, "table_name": table_name}

            dao_classes = await self._idx.entity_dao_candidates()

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
                                await self._idx.entity_merge_accesses_table(
                                    dao_uid,
                                    entity["uid"],
                                    entity.get("table_name") or "",
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
                                await self._idx.entity_merge_accesses_table(
                                    dao_uid,
                                    entity_info["uid"],
                                    entity_info.get("table_name") or "",
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
