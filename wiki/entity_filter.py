"""Entity filtering for Wiki page generation — classify which entities deserve pages."""

from __future__ import annotations

from dataclasses import dataclass

from store.schema import GraphNode, NodeLabel
from wiki.dependency_graph import ModuleGraph
from wiki.models import EntityStrategy


@dataclass
class MethodGroup:
    name: str
    methods: list[GraphNode]


@dataclass
class HubInfo:
    name: str
    domain: str


class LargeClassStrategy:
    METHOD_GROUP_THRESHOLD = 30
    _API_ANNOTATIONS = frozenset(
        {
            "GetMapping",
            "PostMapping",
            "PutMapping",
            "DeleteMapping",
            "PatchMapping",
            "RequestMapping",
        }
    )
    _TASK_ANNOTATIONS = frozenset({"Scheduled", "KafkaListener", "KafkaHandler"})

    def group_methods(self, methods: list[GraphNode]) -> list[MethodGroup]:
        if len(methods) < self.METHOD_GROUP_THRESHOLD:
            return [MethodGroup(name="All Methods", methods=methods)]
        api_methods, task_methods, other_methods = [], [], []
        for m in methods:
            anns = set(m.properties.get("annotations", []) or [])
            ann_simple = {a.lstrip("@").split("(")[0].rsplit(".", 1)[-1] for a in anns}
            if ann_simple & self._API_ANNOTATIONS:
                api_methods.append(m)
            elif ann_simple & self._TASK_ANNOTATIONS:
                task_methods.append(m)
            else:
                other_methods.append(m)
        groups = []
        if api_methods:
            groups.append(MethodGroup(name="API Endpoints", methods=api_methods))
        if task_methods:
            groups.append(MethodGroup(name="Scheduled Tasks", methods=task_methods))
        if other_methods:
            groups.append(MethodGroup(name="Internal Methods", methods=other_methods))
        return groups or [MethodGroup(name="All Methods", methods=methods)]


class HubNodeDetector:
    WHITELIST_ROLES = frozenset({"rpc_provider", "http_controller", "message_listener"})

    def detect_hubs(self, graph: ModuleGraph, percentile: float = 90) -> list[str]:
        module_roles = {m.name: set(m.semantic_roles) for m in graph.modules}
        calls_out: dict[str, list[str]] = {}
        called_by: dict[str, list[str]] = {}
        for e in graph.edges:
            calls_out.setdefault(e.source, []).append(e.target)
            called_by.setdefault(e.target, []).append(e.source)
        degrees = sorted(
            [(m.name, len(calls_out.get(m.name, [])) + len(called_by.get(m.name, []))) for m in graph.modules],
            key=lambda x: x[1],
        )
        if not degrees:
            return []
        n = len(degrees)
        # Index into ascending degree order; 90th percentile threshold is not the max value
        # (which would exclude every node from d > threshold).
        pct_idx = int((percentile / 100) * (n - 1)) if n > 1 else 0
        threshold = degrees[pct_idx][1]
        return [
            m for m, d in degrees if d > threshold and not (module_roles.get(m, set()) & self.WHITELIST_ROLES)
        ]

    def prepare(self, graph: ModuleGraph) -> tuple[ModuleGraph, list[HubInfo]]:
        hubs = self.detect_hubs(graph)
        hub_set = set(hubs)
        reduced_modules = [m for m in graph.modules if m.name not in hub_set]
        reduced_edges = [e for e in graph.edges if e.source not in hub_set and e.target not in hub_set]
        reduced = ModuleGraph(
            modules=reduced_modules,
            edges=reduced_edges,
            entry_points=[ep for ep in graph.entry_points if ep not in hub_set],
        )
        return reduced, [HubInfo(name=h, domain="__infrastructure__") for h in hubs]


class WikiEntityFilter:
    """Classify graph entities into generation strategies."""

    TRIVIAL_LOC_THRESHOLD = 5
    CORE_EDGE_THRESHOLD = 10
    CORE_ROLES = frozenset({"http_controller", "rpc_provider", "message_listener"})

    def classify(self, node: GraphNode, edge_count: int, children_count: int) -> EntityStrategy:
        props = node.properties
        start = props.get("start_line", 0)
        end = props.get("end_line", 0)
        loc = end - start if isinstance(end, int) and isinstance(start, int) else 0
        methods_count = props.get("methods_count", 0)
        if not isinstance(methods_count, int):
            methods_count = 0
        is_interface = props.get("is_interface", False)
        roles_raw = props.get("semantic_roles", [])
        roles = set(roles_raw) if isinstance(roles_raw, list) else set()

        # Core entities always get full pages
        if roles & self.CORE_ROLES or edge_count >= self.CORE_EDGE_THRESHOLD:
            return EntityStrategy.FULL_PAGE

        # MERGE conditions for CLASS
        if node.label == NodeLabel.CLASS:
            # Enum-like: no interface, no methods, small
            if not is_interface and methods_count == 0 and loc < 20:
                return EntityStrategy.MERGE_TO_PARENT
            # Constant holder: no methods, typically only static fields
            if not is_interface and methods_count == 0 and children_count == 0 and loc < 50:
                return EntityStrategy.MERGE_TO_PARENT

        # MERGE conditions for FUNCTION
        if node.label == NodeLabel.FUNCTION:
            if loc < self.TRIVIAL_LOC_THRESHOLD and edge_count == 0:
                return EntityStrategy.MERGE_TO_PARENT

        # Entities with children or many methods deserve standard pages
        if children_count > 0 or methods_count > 3:
            return EntityStrategy.STANDARD_PAGE

        return EntityStrategy.STANDARD_PAGE
