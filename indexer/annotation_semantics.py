"""Pure mapping from annotation names to semantic roles for code graph indexing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticRole(StrEnum):
    """High-level role implied by a framework annotation."""

    RPC_PROVIDER = "rpc_provider"
    RPC_CONSUMER = "rpc_consumer"
    HTTP_CONTROLLER = "http_controller"
    HTTP_ENDPOINT = "http_endpoint"
    SERVICE = "service"
    REPOSITORY = "repository"
    COMPONENT = "component"
    SCHEDULED_TASK = "scheduled_task"
    MESSAGE_LISTENER = "message_listener"
    EVENT_PRODUCER = "event_producer"
    TRANSACTION = "transaction"
    ENTITY = "entity"
    DI_INJECT = "di_inject"


@dataclass(frozen=True)
class AnnotationSemantic:
    """Semantic interpretation of a named annotation."""

    role: SemanticRole
    target: str  # "class" | "method" | "field"
    framework: str


ANNOTATION_SEMANTICS: dict[str, AnnotationSemantic] = {
    # Moa RPC (highest priority)
    "MoaProvider": AnnotationSemantic(SemanticRole.RPC_PROVIDER, "class", "moa"),
    "MoaConsumer": AnnotationSemantic(SemanticRole.RPC_CONSUMER, "method", "moa"),
    # Dubbo
    "DubboService": AnnotationSemantic(SemanticRole.RPC_PROVIDER, "class", "dubbo"),
    "DubboReference": AnnotationSemantic(SemanticRole.RPC_CONSUMER, "method", "dubbo"),
    # Spring Web
    "Controller": AnnotationSemantic(SemanticRole.HTTP_CONTROLLER, "class", "spring"),
    "RestController": AnnotationSemantic(SemanticRole.HTTP_CONTROLLER, "class", "spring"),
    "RequestMapping": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "spring"),
    "GetMapping": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "spring"),
    "PostMapping": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "spring"),
    "PutMapping": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "spring"),
    "DeleteMapping": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "spring"),
    "PatchMapping": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "spring"),
    # Spring Core
    "Service": AnnotationSemantic(SemanticRole.SERVICE, "class", "spring"),
    "Repository": AnnotationSemantic(SemanticRole.REPOSITORY, "class", "spring"),
    "Component": AnnotationSemantic(SemanticRole.COMPONENT, "class", "spring"),
    "Configuration": AnnotationSemantic(SemanticRole.COMPONENT, "class", "spring"),
    "Scheduled": AnnotationSemantic(SemanticRole.SCHEDULED_TASK, "method", "spring"),
    "Transactional": AnnotationSemantic(SemanticRole.TRANSACTION, "method", "spring"),
    # Kafka
    "KafkaListener": AnnotationSemantic(SemanticRole.MESSAGE_LISTENER, "method", "kafka"),
    "KafkaHandler": AnnotationSemantic(SemanticRole.MESSAGE_LISTENER, "method", "kafka"),
    # Python Flask/FastAPI (also matches router.get, api.post, etc. via suffix lookup)
    "app.route": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "flask"),
    "app.get": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "fastapi"),
    "app.post": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "fastapi"),
    "app.put": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "fastapi"),
    "app.delete": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "fastapi"),
    "app.patch": AnnotationSemantic(SemanticRole.HTTP_ENDPOINT, "method", "fastapi"),
    # JPA / Spring Data Entity annotations
    "Entity": AnnotationSemantic(SemanticRole.ENTITY, "class", "jpa"),
    "Table": AnnotationSemantic(SemanticRole.ENTITY, "class", "jpa"),
    "Document": AnnotationSemantic(SemanticRole.ENTITY, "class", "spring-data"),
    "MappedSuperclass": AnnotationSemantic(SemanticRole.ENTITY, "class", "jpa"),
    # Spring DI injection annotations
    "Autowired": AnnotationSemantic(SemanticRole.DI_INJECT, "field", "spring"),
    "Inject": AnnotationSemantic(SemanticRole.DI_INJECT, "field", "javax"),
    "Resource": AnnotationSemantic(SemanticRole.DI_INJECT, "field", "javax"),
}


def lookup_annotation(raw_annotation: str) -> AnnotationSemantic | None:
    """Resolve a raw annotation string (with optional ``@`` and arguments) to semantics.

    Handles both simple names (``@Service``) and fully-qualified names
    (``@org.springframework.stereotype.Service``).  Also handles Python
    dotted decorators like ``@app.route`` and ``@router.get``.
    """
    s = raw_annotation.strip()
    if not s:
        return None
    if s.startswith("@"):
        s = s[1:]
    paren = s.find("(")
    if paren != -1:
        s = s[:paren]
    key = s.strip()
    if not key:
        return None
    result = ANNOTATION_SEMANTICS.get(key)
    if result is not None:
        return result
    # Try simple name (last segment after '.') for Java FQN annotations
    simple_name = key.rsplit(".", 1)[-1]
    if simple_name != key:
        result = ANNOTATION_SEMANTICS.get(simple_name)
        if result is not None:
            return result
    # Try suffix matching for Python router patterns (e.g. "router.get" → "app.get")
    dot_pos = key.find(".")
    if dot_pos != -1:
        suffix = key[dot_pos + 1:]
        for table_key, sem in ANNOTATION_SEMANTICS.items():
            if "." in table_key and table_key.endswith(f".{suffix}"):
                return sem
    return None


def classify_annotations(annotations: list[str]) -> list[str]:
    """Return deduplicated semantic role strings for all annotations that match the table."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in annotations:
        sem = lookup_annotation(raw)
        if sem is None:
            continue
        val = sem.role.value
        if val not in seen:
            seen.add(val)
            out.append(val)
    return out
