"""Post-indexing graph enrichment: API paths, RPC/Kafka metadata, architecture layers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from log import get_logger
from indexer.java_annotation_args import extract_java_annotation_primary_arg
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel, utc_indexed_at_iso

from store.indexer_store import IndexerStore

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

# Prefer specific HTTP verb mappings before generic RequestMapping / route.
_HTTP_ANNOTATION_PRIORITY: tuple[tuple[str, str], ...] = (
    ("GetMapping", "GET"),
    ("PostMapping", "POST"),
    ("PutMapping", "PUT"),
    ("DeleteMapping", "DELETE"),
    ("PatchMapping", "PATCH"),
    ("RequestMapping", "*ALL*"),
    ("route", "*ALL*"),
    ("get", "GET"),
    ("post", "POST"),
    ("put", "PUT"),
    ("delete", "DELETE"),
    ("patch", "PATCH"),
)

_RPC_PROVIDER_NAMES = frozenset({"MoaProvider", "DubboService"})

# Kafka producer call sites: first quoted literal in send/publish-style calls (best-effort).
# Longer send* names before bare "send" so prefixes do not steal the match.
_KAFKA_TOPIC_FROM_SNIPPET = re.compile(
    r"(?:\.|\s)(?:sendSync|sendAsync|sendDefault|convertAndSend|send|publish)\s*\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE | re.DOTALL,
)

# FQN or simple @KafkaListener(...) occurrences in source (inheritance-based consumers).
_KAFKA_LISTENER_ANNOTATION_IN_TEXT = re.compile(r"@(?:[\w.]+\.)?KafkaListener\b")

_IMMOMO_KAFKA_LISTENER_HINTS = (
    "immomo.kafka",
    "autoconfigure.core.kafkalistener",
)


def _kafka_topic_module_node(topic: str) -> GraphNode:
    """Synthetic :Module node for a Kafka topic (cross-repo event tracing)."""
    topic = (topic or "").strip()
    vpath = f"<kafka-topic:{topic}>"
    return GraphNode(
        label=NodeLabel.MODULE,
        properties={
            "name": topic,
            "path": vpath,
            "file": vpath,
            "language": "kafka",
            "kafka_topic": topic,
            "start_line": 0,
            "indexed_at": utc_indexed_at_iso(),
        },
    )


def _topics_from_kafka_producer_snippet(snippet: str | None) -> list[str]:
    if not snippet or not isinstance(snippet, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _KAFKA_TOPIC_FROM_SNIPPET.finditer(snippet):
        t = (m.group(1) or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _parse_annotation_arg(annotation: str) -> str:
    """Extract HTTP path, table name, or RPC ``interfaceClass`` from a Java annotation."""
    return extract_java_annotation_primary_arg(annotation)


def _annotation_simple_name(raw: str) -> str:
    s = raw.strip()
    if s.startswith("@"):
        s = s[1:]
    paren = s.find("(")
    if paren != -1:
        s = s[:paren]
    return s.rsplit(".", 1)[-1].strip()


def _kafka_topic_from_listener(annotation: str) -> str:
    """Best-effort topic string from @KafkaListener(...)."""
    inner_start = annotation.find("(")
    if inner_start == -1:
        return ""
    depth = 0
    end = -1
    for i in range(inner_start, len(annotation)):
        if annotation[i] == "(":
            depth += 1
        elif annotation[i] == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return ""
    inner = annotation[inner_start + 1 : end]
    m = re.search(
        r"topics\s*=\s*(?:\{([^}]*)\}|([\"'])([^\"']+)\2)",
        inner,
        re.IGNORECASE,
    )
    if m:
        if m.group(3) is not None:
            return m.group(3).strip()
        brace = m.group(1) or ""
        q = re.search(r'["\']((?:[^"\'\\]|\\.)*)["\']', brace)
        if q:
            return q.group(1)
    return _parse_annotation_arg(annotation)


def _strip_java_type_generics(type_ref: str) -> str:
    """Remove top-level ``<...>`` generic arguments from a Java type reference string."""
    depth = 0
    out: list[str] = []
    for c in type_ref:
        if c == "<":
            depth += 1
        elif c == ">":
            if depth > 0:
                depth -= 1
        elif depth == 0:
            out.append(c)
    return "".join(out).strip()


def _java_extends_company_kafka_listener(base_classes: list[object] | None) -> bool:
    """True when a class extends the Immomo ``KafkaListener`` base (not the Spring annotation)."""
    for b in base_classes or []:
        raw = b.strip() if isinstance(b, str) else str(b).strip()
        if not raw:
            continue
        base = _strip_java_type_generics(raw)
        low = base.lower()
        if "kafkalistener" not in low:
            continue
        if any(h in low for h in _IMMOMO_KAFKA_LISTENER_HINTS):
            return True
        if base == "KafkaListener" or base.endswith(".KafkaListener"):
            if "springframework.kafka.annotation" in low:
                continue
            return True
    return False


def _extract_kafka_listener_topics_from_java_text(text: str | None) -> list[str]:
    """Collect topic strings from any ``@KafkaListener`` annotations embedded in Java source."""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _KAFKA_LISTENER_ANNOTATION_IN_TEXT.finditer(text):
        idx = m.start()
        j = m.end()
        while j < len(text) and text[j].isspace():
            j += 1
        if j >= len(text) or text[j] != "(":
            continue
        depth = 0
        end_pos = -1
        for k in range(j, len(text)):
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    end_pos = k
                    break
        if end_pos == -1:
            continue
        ann = text[idx : end_pos + 1]
        topic = _kafka_topic_from_listener(ann)
        if topic and topic not in seen:
            seen.add(topic)
            out.append(topic)
    return out


def _join_api_paths(base: str, rel: str) -> str:
    base = (base or "").strip()
    rel = (rel or "").strip()
    if not base:
        return rel if rel.startswith("/") else ("/" + rel if rel else "")
    if not rel:
        return base.rstrip("/") or "/"
    base_norm = base.rstrip("/")
    rel_norm = rel.lstrip("/")
    if not rel_norm:
        return base_norm or "/"
    if base_norm == "" or base_norm == "/":
        return "/" + rel_norm
    return base_norm + "/" + rel_norm


def _pick_http_annotation(
    annotations: list[str] | None,
) -> tuple[str | None, str | None, str]:
    """Return (raw_annotation, http_method, path_segment) for the best HTTP mapping."""
    if not annotations:
        return None, None, ""
    priority_index = {name: i for i, (name, _) in enumerate(_HTTP_ANNOTATION_PRIORITY)}
    best: tuple[int, int, int, str, str] | None = None
    # (pr_idx, list_index, neg_simple_len, raw, method)
    for idx, raw in enumerate(annotations):
        simple = _annotation_simple_name(raw)
        method: str | None = None
        pr_idx = 999
        for name, m in _HTTP_ANNOTATION_PRIORITY:
            if simple == name or simple.endswith("." + name):
                method = m
                pr_idx = priority_index[name]
                break
        if method is None:
            continue
        # Lower pr_idx = higher priority; earlier annotation wins ties
        neg_spec = -len(simple)
        cand = (pr_idx, idx, neg_spec, raw, method)
        if best is None or cand[:3] < best[:3]:
            best = cand
    if best is None:
        return None, None, ""
    _, _, _, raw_ann, meth = best
    return raw_ann, meth, _parse_annotation_arg(raw_ann or "")


def _class_request_mapping_base(class_annotations: list[str] | None) -> str:
    if not class_annotations:
        return ""
    for raw in class_annotations:
        simple = _annotation_simple_name(raw)
        if simple in ("RequestMapping",) or simple.endswith(".RequestMapping"):
            return _parse_annotation_arg(raw)
    return ""


def _classify_architecture_layer(
    semantic_roles: list[str] | None,
    fqn: str | None,
) -> str:
    sr = set(semantic_roles or [])
    if "http_controller" in sr:
        return "presentation"
    if "rpc_provider" in sr:
        return "rpc"
    if "service" in sr:
        return "business"
    if "repository" in sr:
        return "data_access"
    if "message_listener" in sr:
        return "messaging"
    if "component" in sr or "scheduled_task" in sr:
        return "infrastructure"

    f = fqn or ""
    lower = f.lower()
    if ".controller." in lower or ".controllers." in lower:
        return "presentation"
    if ".service." in lower or ".services." in lower:
        return "business"
    if ".dao." in lower or ".repository." in lower or ".mapper." in lower:
        return "data_access"
    if ".model." in lower or ".entity." in lower or ".dto." in lower:
        return "model"
    if ".config." in lower or ".configuration." in lower:
        return "infrastructure"

    # Extended FQN heuristics from production package analysis (first match wins).
    # Messaging — narrow matchers: listener/producer/consumer are unambiguous;
    # .event./.events. only count as messaging when combined with kafka/mq/messaging
    # to avoid misclassifying domain-event packages.
    if (
        ".listener." in lower
        or ".listeners." in lower
        or ".producer." in lower
        or ".consumer." in lower
    ):
        return "messaging"
    if (".event." in lower or ".events." in lower) and (
        ".kafka." in lower or ".mq." in lower or ".messaging." in lower
    ):
        return "messaging"
    # RPC (internal wrappers / integration facades)
    if ".moa." in lower or ".external." in lower:
        return "rpc"
    # Business (org-style packages and request handlers)
    if ".internal." in lower or ".handler." in lower or ".handlers." in lower:
        return "business"
    # Data access (short "repo" segment distinct from ".repository.")
    if ".repo." in lower:
        return "data_access"
    # Model / API shapes / value types (including domain events)
    if (
        ".bean." in lower
        or ".resp." in lower
        or ".req." in lower
        or ".request." in lower
        or ".response." in lower
        or ".param." in lower
        or ".constant." in lower
        or ".constants." in lower
        or ".enum." in lower
        or ".enums." in lower
        or ".vo." in lower
        or ".pojo." in lower
        or ".domain." in lower
        or ".event." in lower
        or ".events." in lower
    ):
        return "model"
    # Infrastructure / cross-cutting helpers
    if (
        ".util." in lower
        or ".utils." in lower
        or ".convert." in lower
        or ".converter." in lower
        or ".adapter." in lower
        or ".wrapper." in lower
        or ".autoconf." in lower
        or ".autoconfigure." in lower
        or ".error." in lower
        or ".exception." in lower
        or ".exceptions." in lower
        or ".bi." in lower
        or ".interceptor." in lower
        or ".filter." in lower
        or ".aspect." in lower
    ):
        return "infrastructure"

    return "unknown"


class GraphEnricher:
    """Post-indexing enrichment: derives API endpoint info and architecture layers from annotations."""

    def __init__(self, store: FalkorDBStore, indexer_store: IndexerStore | None = None) -> None:
        self._store = store
        self._idx = indexer_store or IndexerStore(store)

    async def enrich(self) -> dict[str, int]:
        """Run all enrichment passes. Returns counts of enriched nodes."""
        api_count = await self._enrich_api_endpoints()
        layer_count = await self._enrich_architecture_layers()
        rpc_contract_count = await self._enrich_rpc_contracts()
        event_count = await self._enrich_event_tracking()
        return {
            "api_endpoints": api_count,
            "architecture_layers": layer_count,
            "rpc_contracts": rpc_contract_count,
            "event_tracking": event_count,
        }

    async def _enrich_api_endpoints(self) -> int:
        count = 0
        try:
            res = await self._idx.enrich_scan_http_endpoint_rows()
            for row in res.data:
                uid = row.get("uid")
                if not uid:
                    continue
                f_ann = row.get("f_ann") or []
                c_ann = row.get("c_ann") or []
                if not isinstance(f_ann, list):
                    f_ann = []
                if not isinstance(c_ann, list):
                    c_ann = []
                base = _class_request_mapping_base(c_ann)
                _raw, method, rel_path = _pick_http_annotation(f_ann)
                if method is None:
                    method = "*ALL*"
                full_path = _join_api_paths(base, rel_path)
                try:
                    await self._idx.enrich_set_function_http_props(uid, method, full_path)
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_http_failed", uid=uid, error=str(exc))

            res_rpc = await self._idx.enrich_scan_rpc_provider_classes()
            for row in res_rpc.data:
                uid = row.get("uid")
                if not uid:
                    continue
                anns = row.get("annotations") or []
                if not isinstance(anns, list):
                    anns = []
                iface = ""
                for raw in anns:
                    simple = _annotation_simple_name(raw)
                    if simple in _RPC_PROVIDER_NAMES:
                        iface = _parse_annotation_arg(raw)
                        if iface:
                            break
                try:
                    await self._idx.enrich_set_class_rpc_interface(uid, iface)
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_rpc_failed", uid=uid, error=str(exc))

            res_k = await self._idx.enrich_scan_kafka_listener_functions()
            for row in res_k.data:
                uid = row.get("uid")
                if not uid:
                    continue
                anns = row.get("annotations") or []
                if not isinstance(anns, list):
                    anns = []
                topic = ""
                for raw in anns:
                    simple = _annotation_simple_name(raw)
                    if simple in ("KafkaListener", "KafkaHandler") or simple.endswith(
                        ".KafkaListener",
                    ) or simple.endswith(".KafkaHandler"):
                        topic = _kafka_topic_from_listener(raw)
                        if topic:
                            break
                if not topic:
                    for raw in anns:
                        if "KafkaListener" in raw or "KafkaHandler" in raw:
                            topic = _kafka_topic_from_listener(raw)
                            if topic:
                                break
                try:
                    await self._idx.enrich_set_function_kafka_topic(uid, topic)
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_kafka_failed", uid=uid, error=str(exc))

            res_k_ext = await self._idx.enrich_scan_kafka_listener_subclass_methods()
            for row in res_k_ext.data:
                uid = row.get("uid")
                if not uid:
                    continue
                bases = row.get("base_classes") or []
                if not isinstance(bases, list):
                    bases = []
                if not _java_extends_company_kafka_listener(bases):
                    continue
                anns = row.get("annotations") or []
                if not isinstance(anns, list):
                    anns = []
                topic = ""
                for raw in anns:
                    simple = _annotation_simple_name(raw)
                    if simple in ("KafkaListener", "KafkaHandler") or simple.endswith(
                        ".KafkaListener",
                    ) or simple.endswith(".KafkaHandler"):
                        topic = _kafka_topic_from_listener(raw)
                        if topic:
                            break
                if not topic:
                    for raw in anns:
                        if "KafkaListener" in raw or "KafkaHandler" in raw:
                            topic = _kafka_topic_from_listener(raw)
                            if topic:
                                break
                if not topic:
                    combined = (row.get("class_snippet") or "") + "\n" + (row.get("func_snippet") or "")
                    topics = _extract_kafka_listener_topics_from_java_text(combined)
                    if topics:
                        topic = topics[0]
                if not topic:
                    continue
                try:
                    await self._idx.enrich_set_function_kafka_topic(uid, topic)
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_kafka_inherit_failed", uid=uid, error=str(exc))

        except Exception as exc:
            log.warning("graph_enrich_api_pass_error", error=str(exc))
        return count

    async def _enrich_architecture_layers(self) -> int:
        count = 0
        try:
            res = await self._idx.enrich_list_classes_with_semantic_roles()
            for row in res.data:
                uid = row.get("uid")
                if not uid:
                    continue
                sr = row.get("sr")
                if sr is not None and not isinstance(sr, list):
                    sr = None
                layer = _classify_architecture_layer(sr, row.get("fqn"))
                try:
                    prop = await self._idx.enrich_set_class_layer_and_functions(uid, layer)
                    fn = 0
                    if prop.data:
                        fn = int(prop.data[0].get("fn") or 0)
                    count += 1 + fn
                except Exception as exc:
                    log.warning("graph_enrich_layer_failed", uid=uid, error=str(exc))
        except Exception as exc:
            log.warning("graph_enrich_layer_pass_error", error=str(exc))
        return count

    async def _enrich_rpc_contracts(self) -> int:
        """Mark RPC interface classes and store method signatures for contract surfaces."""
        count = 0
        try:
            await self._idx.enrich_reset_rpc_contract_flags()
            res = await self._idx.enrich_rpc_provider_interface_candidates()
            for row in res.data:
                uid = row.get("uid")
                if not uid:
                    continue
                mres = await self._idx.enrich_iface_contract_methods(uid)
                methods: list[str] = []
                for mr in mres.data:
                    sig = (mr.get("signature") or "").strip()
                    name = (mr.get("name") or "").strip()
                    methods.append(sig if sig else name)
                try:
                    await self._idx.enrich_set_iface_rpc_contract(uid, methods)
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_rpc_contract_failed", uid=uid, error=str(exc))
        except Exception as exc:
            log.warning("graph_enrich_rpc_contracts_pass_error", error=str(exc))
        return count

    async def _enrich_event_tracking(self) -> int:
        """Kafka EVENT_CONSUMES / EVENT_PRODUCES edges to synthetic topic :Module nodes."""
        count = 0
        try:
            await self._idx.enrich_delete_all_event_produces_edges()
            await self._idx.enrich_delete_all_event_consumes_edges()

            res_consume = await self._idx.enrich_kafka_consumer_functions_with_topic()
            for row in res_consume.data:
                func_uid = row.get("uid")
                topic = (row.get("topic") or "").strip()
                if not func_uid or not topic:
                    continue
                mod = _kafka_topic_module_node(topic)
                try:
                    await self._store.upsert_node(mod)
                    await self._store.upsert_edge(
                        GraphEdge(
                            edge_type=EdgeType.EVENT_CONSUMES,
                            source_uid=func_uid,
                            target_uid=mod.uid,
                        ),
                    )
                    count += 1
                except Exception as exc:
                    log.warning(
                        "graph_enrich_event_consume_failed",
                        uid=func_uid,
                        topic=topic,
                        error=str(exc),
                    )

            res_producers = await self._idx.enrich_kafka_producer_call_rows()
            producer_uids: set[str] = set()
            for row in res_producers.data:
                u = row.get("uid")
                if u:
                    producer_uids.add(str(u))
            for row in res_producers.data:
                func_uid = row.get("uid")
                if not func_uid:
                    continue
                topics = _topics_from_kafka_producer_snippet(row.get("snippet"))
                for topic in topics:
                    mod = _kafka_topic_module_node(topic)
                    try:
                        await self._store.upsert_node(mod)
                        await self._store.upsert_edge(
                            GraphEdge(
                                edge_type=EdgeType.EVENT_PRODUCES,
                                source_uid=func_uid,
                                target_uid=mod.uid,
                            ),
                        )
                        count += 1
                    except Exception as exc:
                        log.warning(
                            "graph_enrich_event_produce_failed",
                            uid=func_uid,
                            topic=topic,
                            error=str(exc),
                        )

            res_momo = await self._idx.enrich_kafka_momo_producer_functions()
            for row in res_momo.data:
                func_uid = row.get("uid")
                if not func_uid or str(func_uid) in producer_uids:
                    continue
                topics = _topics_from_kafka_producer_snippet(row.get("snippet"))
                for topic in topics:
                    mod = _kafka_topic_module_node(topic)
                    try:
                        await self._store.upsert_node(mod)
                        await self._store.upsert_edge(
                            GraphEdge(
                                edge_type=EdgeType.EVENT_PRODUCES,
                                source_uid=func_uid,
                                target_uid=mod.uid,
                            ),
                        )
                        count += 1
                    except Exception as exc:
                        log.warning(
                            "graph_enrich_event_produce_momo_failed",
                            uid=func_uid,
                            topic=topic,
                            error=str(exc),
                        )
        except Exception as exc:
            log.warning("graph_enrich_event_tracking_pass_error", error=str(exc))
        return count
