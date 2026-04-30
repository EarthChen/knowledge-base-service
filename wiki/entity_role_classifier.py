"""Two-phase entity role classifier for Wiki generation.

Phase 1: Deterministic rules (fast path) — name patterns, annotations, trivial checks.
Phase 2: Business logic density scoring — weighted score across 4 dimensions.
"""
from __future__ import annotations

import re
from enum import StrEnum

from store.schema import GraphNode
from log import get_logger

log = get_logger(__name__)


class WikiEntityRole(StrEnum):
    HAS_BUSINESS_LOGIC = "has_business_logic"
    SUPPORTING = "supporting"
    DATA_MODEL = "data_model"
    FRAMEWORK_NOISE = "framework_noise"


_DATA_SUFFIXES = re.compile(
    r"(DTO|VO|PO|Bo|Param|Request|Response|Entity|Form|Query|Result)$",
    re.IGNORECASE,
)
_DATA_ANNOTATIONS = frozenset({
    "Data", "Value", "Builder", "Getter", "Setter", "AllArgsConstructor",
    "NoArgsConstructor", "ToString", "EqualsAndHashCode",
})
_NOISE_ONLY_ANNOTATIONS = frozenset({
    "Component", "Configuration", "EnableAutoConfiguration",
    "SpringBootApplication", "EnableDiscoveryClient",
})
_BIZ_ROLE_ANNOTATIONS = frozenset({
    "RestController", "Controller", "Service", "KafkaListener",
    "RabbitListener", "Scheduled",
})
_REPO_ANNOTATIONS = frozenset({"Repository", "Mapper"})
_CORE_SEMANTIC_ROLES = frozenset({
    "http_controller", "rpc_provider", "message_listener",
})


def _simplify_annotations(raw: list[str] | None) -> set[str]:
    if not raw:
        return set()
    return {a.lstrip("@").split("(")[0].rsplit(".", 1)[-1] for a in raw}


class EntityRoleClassifier:
    SCORE_THRESHOLD_BIZ = 40
    SCORE_THRESHOLD_SUPPORTING = 15

    def classify(
        self,
        node: GraphNode,
        *,
        edge_count: int = 0,
        children_count: int = 0,
    ) -> WikiEntityRole:
        phase1 = self._phase1_deterministic(node, edge_count)
        if phase1 is not None:
            return phase1
        score = self.compute_score(node, edge_count=edge_count, children_count=children_count)
        if score >= self.SCORE_THRESHOLD_BIZ:
            return WikiEntityRole.HAS_BUSINESS_LOGIC
        if score >= self.SCORE_THRESHOLD_SUPPORTING:
            return WikiEntityRole.SUPPORTING
        return WikiEntityRole.DATA_MODEL

    def compute_score(
        self,
        node: GraphNode,
        *,
        edge_count: int = 0,
        children_count: int = 0,
    ) -> float:
        props = node.properties
        methods_count = int(props.get("methods_count", 0) or 0)
        start = int(props.get("start_line", 0) or 0)
        end = int(props.get("end_line", 0) or 0)
        loc = max(end - start, 0)
        annotations = _simplify_annotations(props.get("annotations"))
        roles_raw = props.get("semantic_roles", [])
        roles = set(roles_raw) if isinstance(roles_raw, list) else set()

        effective_methods = max(methods_count - self._estimate_getters(node), 0)
        dim_methods = min(effective_methods / 5.0, 1.0) * 35
        dim_graph = min(edge_count / 20.0, 1.0) * 25
        dim_role = self._score_semantic_role(annotations, roles, methods_count)
        dim_loc = min(loc / 200.0, 1.0) * 15

        return dim_methods + dim_graph + dim_role + dim_loc

    def _phase1_deterministic(
        self, node: GraphNode, edge_count: int,
    ) -> WikiEntityRole | None:
        props = node.properties
        name = str(props.get("name", ""))
        methods_count = int(props.get("methods_count", 0) or 0)
        start = int(props.get("start_line", 0) or 0)
        end = int(props.get("end_line", 0) or 0)
        loc = max(end - start, 0)
        is_enum = bool(props.get("is_enum", False))
        annotations = _simplify_annotations(props.get("annotations"))

        if annotations & _DATA_ANNOTATIONS and methods_count <= 3:
            return WikiEntityRole.DATA_MODEL
        if _DATA_SUFFIXES.search(name):
            return WikiEntityRole.DATA_MODEL
        if is_enum or name.endswith("Enum") or name.endswith("Constants"):
            return WikiEntityRole.DATA_MODEL
        implements = props.get("implements", [])
        if isinstance(implements, list) and "Serializable" in implements and methods_count == 0:
            return WikiEntityRole.DATA_MODEL
        if loc < 10 and methods_count == 0 and edge_count == 0:
            return WikiEntityRole.FRAMEWORK_NOISE
        if annotations and annotations <= _NOISE_ONLY_ANNOTATIONS and methods_count == 0:
            return WikiEntityRole.FRAMEWORK_NOISE
        return None

    @staticmethod
    def _estimate_getters(node: GraphNode) -> int:
        annotations = _simplify_annotations(node.properties.get("annotations"))
        if annotations & {"Data", "Getter", "Setter"}:
            return int(node.properties.get("methods_count", 0) or 0) // 2
        return 0

    @staticmethod
    def _score_semantic_role(
        annotations: set[str], roles: set[str], methods_count: int,
    ) -> float:
        if roles & _CORE_SEMANTIC_ROLES:
            return 25.0
        if annotations & _BIZ_ROLE_ANNOTATIONS:
            return 20.0
        if annotations & _REPO_ANNOTATIONS:
            return 15.0
        if "Component" in annotations and methods_count > 3:
            return 10.0
        if methods_count > 0:
            return 5.0
        return 0.0
