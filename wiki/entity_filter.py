"""Entity filtering for Wiki page generation — classify which entities deserve pages."""

from __future__ import annotations

from store.schema import GraphNode, NodeLabel
from wiki.models import EntityStrategy


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

        if roles & self.CORE_ROLES or edge_count >= self.CORE_EDGE_THRESHOLD:
            return EntityStrategy.FULL_PAGE

        if node.label == NodeLabel.CLASS:
            if not is_interface and methods_count == 0 and loc < 20:
                return EntityStrategy.MERGE_TO_PARENT

        if node.label == NodeLabel.FUNCTION:
            if loc < self.TRIVIAL_LOC_THRESHOLD and edge_count == 0:
                return EntityStrategy.MERGE_TO_PARENT

        return EntityStrategy.STANDARD_PAGE
