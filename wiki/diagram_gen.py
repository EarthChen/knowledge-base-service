"""Deterministic Mermaid diagram generation from graph nodes and edges."""

from __future__ import annotations

import html
import re

from store.schema import EdgeType, GraphEdge, GraphNode
from wiki.models import DiagramType, WikiDiagram

MAX_DIAGRAM_NODES = 15


def _escape_label(text: str) -> str:
    return html.escape(text, quote=False)


def _display_name_from_uid(uid: str) -> str:
    parts = uid.rsplit(":", 2)
    if len(parts) >= 3:
        return str(parts[-2])
    return uid


def _sanitize_class_id(raw: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    if not s:
        return "Cls"
    if s[0].isdigit():
        return "C_" + s
    return s


def _unique_class_ids(uids: set[str]) -> dict[str, str]:
    """Map each uid to a unique Mermaid-safe class identifier."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for uid in sorted(uids):
        base = _sanitize_class_id(_display_name_from_uid(uid))
        candidate = base
        n = 0
        while candidate in used:
            n += 1
            candidate = f"{base}_{n}"
        used.add(candidate)
        out[uid] = candidate
    return out


def _edge_degree(uid: str, edges: list[GraphEdge]) -> int:
    n = 0
    for e in edges:
        if e.source_uid == uid or e.target_uid == uid:
            n += 1
    return n


def _truncate_nodes(
    center_uid: str,
    node_uids: set[str],
    rank_edges: list[GraphEdge],
    max_nodes: int = MAX_DIAGRAM_NODES,
) -> tuple[set[str], int]:
    """Keep ``center_uid`` plus highest-degree neighbors; return (visible, collapsed_count)."""
    if len(node_uids) <= max_nodes:
        return set(node_uids), 0

    others = sorted(
        node_uids - {center_uid},
        key=lambda u: (-_edge_degree(u, rank_edges), u),
    )
    keep_n = max_nodes - 1
    visible = {center_uid} | set(others[:keep_n])
    collapsed = len(node_uids) - len(visible)
    return visible, collapsed


def _allocate_flow_ids(visible: set[str], center_uid: str) -> dict[str, str]:
    ordered: list[str] = []
    if center_uid in visible:
        ordered.append(center_uid)
    ordered.extend(sorted(visible - {center_uid}))
    return {uid: f"n{i}" for i, uid in enumerate(ordered)}


def _flowchart_td(
    focal_uid: str,
    relevant_edges: list[GraphEdge],
    diagram_type: DiagramType,
) -> WikiDiagram:
    nodes: set[str] = {focal_uid}
    for e in relevant_edges:
        nodes.add(e.source_uid)
        nodes.add(e.target_uid)

    visible, collapsed = _truncate_nodes(focal_uid, nodes, relevant_edges or [])
    idmap = _allocate_flow_ids(visible, focal_uid)

    lines: list[str] = ["flowchart TD"]
    for uid in sorted(visible, key=lambda u: idmap[u]):
        nid = idmap[uid]
        label = _escape_label(_display_name_from_uid(uid))
        lines.append(f'    {nid}["{label}"]')

    ov_id = ""
    if collapsed > 0:
        ov_id = "OVFLW"
        lbl = _escape_label(f"... and {collapsed} more")
        lines.append(f'    {ov_id}["{lbl}"]')

    for e in relevant_edges:
        su, tu = e.source_uid, e.target_uid
        sid = idmap.get(su)
        tid = idmap.get(tu)
        if sid and tid:
            lines.append(f"    {sid} --> {tid}")
        elif sid and not tid and ov_id:
            lines.append(f"    {sid} --> {ov_id}")
        elif not sid and tid and ov_id:
            lines.append(f"    {ov_id} --> {tid}")

    content = "\n".join(lines) + "\n"
    return WikiDiagram(diagram_type=diagram_type, content=content, title="")


def generate_class_diagram(class_node: GraphNode, edges: list[GraphEdge]) -> WikiDiagram:
    focal_uid = class_node.uid
    inherit_edges = [e for e in edges if e.edge_type == EdgeType.INHERITS]
    contain_edges = [e for e in edges if e.edge_type == EdgeType.CONTAINS and e.source_uid == focal_uid]

    class_nodes: set[str] = {focal_uid}
    for e in inherit_edges:
        class_nodes.add(e.source_uid)
        class_nodes.add(e.target_uid)

    rank_edges = inherit_edges if inherit_edges else []
    visible_class, collapsed_inherit = _truncate_nodes(
        focal_uid,
        class_nodes,
        rank_edges if rank_edges else edges,
    )

    id_map = _unique_class_ids(visible_class)

    method_names = [
        _escape_label(_display_name_from_uid(e.target_uid))
        for e in sorted(contain_edges, key=lambda x: x.target_uid)
    ]

    lines: list[str] = ["classDiagram"]

    if collapsed_inherit > 0:
        lbl = _escape_label(f"... and {collapsed_inherit} more")
        lines.append(f'    class OVFLW["{lbl}"]')

    focal_sid = id_map[focal_uid]
    focal_raw = _display_name_from_uid(focal_uid)
    if method_names:
        lines.append(f'    class {focal_sid}["{_escape_label(focal_raw)}"] {{')
        for m in method_names:
            lines.append(f"        +{m}()")
        lines.append("    }")
    else:
        lines.append(f'    class {focal_sid}["{_escape_label(focal_raw)}"]')

    for uid in sorted(visible_class - {focal_uid}):
        sid = id_map[uid]
        raw = _display_name_from_uid(uid)
        lines.append(f'    class {sid}["{_escape_label(raw)}"]')

    for e in inherit_edges:
        parent_uid, child_uid = e.target_uid, e.source_uid
        if parent_uid not in visible_class or child_uid not in visible_class:
            continue
        ps = id_map[parent_uid]
        cs = id_map[child_uid]
        lines.append(f"    {ps} <|-- {cs}")

    content = "\n".join(lines) + "\n"
    return WikiDiagram(diagram_type=DiagramType.CLASS_DIAGRAM, content=content, title="")


def generate_dependency_graph(module_node: GraphNode, edges: list[GraphEdge]) -> WikiDiagram:
    imp_edges = [e for e in edges if e.edge_type == EdgeType.IMPORTS]
    return _flowchart_td(module_node.uid, imp_edges, DiagramType.DEPENDENCY_GRAPH)


def generate_call_flowchart(entry_node: GraphNode, edges: list[GraphEdge]) -> WikiDiagram:
    call_edges = [e for e in edges if e.edge_type == EdgeType.CALLS]
    return _flowchart_td(entry_node.uid, call_edges, DiagramType.FLOWCHART)

