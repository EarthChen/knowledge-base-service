"""Post-indexing graph enrichment: API paths, RPC/Kafka metadata, architecture layers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from log import get_logger

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


def _parse_annotation_arg(annotation: str) -> str:
    """Extract first string argument from annotation like @GetMapping("/api/users")."""
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
    # topics = "foo" style — first quoted literal after optional attr name
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
    return "unknown"


class GraphEnricher:
    """Post-indexing enrichment: derives API endpoint info and architecture layers from annotations."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def enrich(self) -> dict[str, int]:
        """Run all enrichment passes. Returns counts of enriched nodes."""
        api_count = await self._enrich_api_endpoints()
        layer_count = await self._enrich_architecture_layers()
        return {"api_endpoints": api_count, "architecture_layers": layer_count}

    async def _enrich_api_endpoints(self) -> int:
        count = 0
        try:
            q_http = (
                "MATCH (f:Function) "
                "WHERE f.semantic_roles IS NOT NULL AND 'http_endpoint' IN f.semantic_roles "
                "OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) "
                "RETURN f.uid AS uid, f.annotations AS f_ann, c.annotations AS c_ann"
            )
            res = await self._store.execute_query(q_http)
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
                    await self._store.execute_query(
                        "MATCH (f:Function) WHERE f.uid = $uid "
                        "SET f.http_method = $method, f.api_path = $path",
                        {"uid": uid, "method": method, "path": full_path},
                    )
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_http_failed", uid=uid, error=str(exc))

            q_rpc = (
                "MATCH (c:Class) "
                "WHERE c.semantic_roles IS NOT NULL AND 'rpc_provider' IN c.semantic_roles "
                "RETURN c.uid AS uid, c.annotations AS annotations"
            )
            res_rpc = await self._store.execute_query(q_rpc)
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
                    await self._store.execute_query(
                        "MATCH (c:Class) WHERE c.uid = $uid SET c.rpc_interface = $iface",
                        {"uid": uid, "iface": iface},
                    )
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_rpc_failed", uid=uid, error=str(exc))

            q_kafka = (
                "MATCH (f:Function) "
                "WHERE f.semantic_roles IS NOT NULL AND 'message_listener' IN f.semantic_roles "
                "RETURN f.uid AS uid, f.annotations AS annotations"
            )
            res_k = await self._store.execute_query(q_kafka)
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
                    await self._store.execute_query(
                        "MATCH (f:Function) WHERE f.uid = $uid SET f.kafka_topic = $topic",
                        {"uid": uid, "topic": topic},
                    )
                    count += 1
                except Exception as exc:
                    log.warning("graph_enrich_kafka_failed", uid=uid, error=str(exc))

        except Exception as exc:
            log.warning("graph_enrich_api_pass_error", error=str(exc))
        return count

    async def _enrich_architecture_layers(self) -> int:
        count = 0
        try:
            res = await self._store.execute_query(
                "MATCH (c:Class) RETURN c.uid AS uid, c.semantic_roles AS sr, c.fqn AS fqn",
            )
            for row in res.data:
                uid = row.get("uid")
                if not uid:
                    continue
                sr = row.get("sr")
                if sr is not None and not isinstance(sr, list):
                    sr = None
                layer = _classify_architecture_layer(sr, row.get("fqn"))
                try:
                    prop = await self._store.execute_query(
                        "MATCH (c:Class) WHERE c.uid = $uid "
                        "SET c.architecture_layer = $layer "
                        "WITH c "
                        "MATCH (c)-[:CONTAINS]->(f:Function) "
                        "SET f.architecture_layer = $layer "
                        "RETURN count(f) AS fn",
                        {"uid": uid, "layer": layer},
                    )
                    fn = 0
                    if prop.data:
                        fn = int(prop.data[0].get("fn") or 0)
                    count += 1 + fn
                except Exception as exc:
                    log.warning("graph_enrich_layer_failed", uid=uid, error=str(exc))
        except Exception as exc:
            log.warning("graph_enrich_layer_pass_error", error=str(exc))
        return count
