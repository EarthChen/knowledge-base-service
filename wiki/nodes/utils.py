"""Shared helpers for wiki pipeline nodes."""

import re
from typing import Any

from core.config import get_settings
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.data_collector import PageData
from wiki.models import SourceLocation
from wiki.snippet_selector import select_key_snippets as _select_key_snippets_source

select_key_snippets = _select_key_snippets_source

_COMPOSE_CONCURRENCY = get_settings().wiki.compose_concurrency
_MAX_LEAF_MODULES = 15


def _normalize_domain_tree(raw_tree: list | None) -> list[dict[str, Any]]:
    """Convert HierarchicalDecomposer output (DomainNode list) to plain dicts."""
    if not raw_tree:
        return []
    result = []
    for node in raw_tree:
        if hasattr(node, "name"):
            d = {
                "name": getattr(node, "name", ""),
                "description": getattr(node, "description", ""),
                "modules": [m.name if hasattr(m, "name") else str(m) for m in getattr(node, "modules", [])],
                "children": _normalize_domain_tree(getattr(node, "children", [])),
            }
        elif isinstance(node, dict):
            d = {
                "name": node.get("name", ""),
                "description": node.get("description", ""),
                "modules": node.get("modules", []),
                "children": _normalize_domain_tree(node.get("children", [])),
            }
        else:
            continue
        result.append(d)
    return result


def _detect_oversized_leaves(domain_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return leaf domains whose module count exceeds _MAX_LEAF_MODULES.

    Uses the same leaf criterion as ``_collect_leaf_domains`` but returns the
    original dict nodes from ``domain_tree`` so callers can mutate the tree in place.
    """
    oversized: list[dict[str, Any]] = []
    for node in domain_tree:
        children = node.get("children") or []
        if not children:
            modules = node.get("modules", [])
            if len(modules) > _MAX_LEAF_MODULES:
                oversized.append(node)
        else:
            oversized.extend(_detect_oversized_leaves(children))
    return oversized


def _collect_leaf_domains(tree: list[dict[str, Any]], parent: str = "root") -> list[dict[str, Any]]:
    """Recursively collect leaf domains (no children or children are empty)."""
    leaves: list[dict[str, Any]] = []
    for node in tree:
        children = node.get("children", [])
        node_with_parent = {**node, "parent": parent}
        if not children:
            leaves.append(node_with_parent)
        else:
            leaves.extend(_collect_leaf_domains(children, parent=node.get("name", "unknown")))
    return leaves


_OVERVIEW_SECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^##\s*业务概述\s*$", re.MULTILINE),
    re.compile(r"^##\s*Overview\s*$", re.MULTILINE),
    re.compile(r"^##\s*Summary\s*$", re.MULTILINE),
    re.compile(r"^##\s*概述\s*$", re.MULTILINE),
)

_SUMMARY_MAX_LEN = 300


def _normalize_pages_map(pages: Any) -> dict[str, dict[str, Any]]:
    """Build path -> page dict whether ``pages`` is a mapping or list of page dicts."""
    if isinstance(pages, dict):
        return {str(k): v for k, v in pages.items() if isinstance(v, dict)}
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(pages, list):
        return out
    for p in pages:
        if not isinstance(p, dict):
            continue
        path = p.get("path")
        if path:
            out[str(path)] = p
    return out


def _find_page_for_leaf_domain(
    pages_by_path: dict[str, dict[str, Any]], domain_name: str
) -> dict[str, Any] | None:
    """Locate the wiki page for a leaf domain (path contains domain slug)."""
    if not domain_name:
        return None
    preferred = f"wiki/{domain_name}"
    if preferred in pages_by_path:
        return pages_by_path[preferred]
    if domain_name in pages_by_path:
        return pages_by_path[domain_name]
    suffix = f"/{domain_name}"
    for path, page in pages_by_path.items():
        if path == domain_name or path.rstrip("/").endswith(suffix):
            return page
    return None


def _extract_summary_from_content(content: str) -> str:
    """Rule-based summary: overview section, then first paragraph after first heading, else truncate."""
    text = content or ""
    if not text.strip():
        return ""

    for pattern in _OVERVIEW_SECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            start = match.end()
            remainder = text[start:]
            stop = remainder.find("\n## ")
            body = remainder if stop < 0 else remainder[:stop]
            out = body.strip()
            if out:
                return out[:_SUMMARY_MAX_LEN]

    lines = text.splitlines()
    heading_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("#"):
            heading_idx = idx
            break
    if heading_idx is not None:
        i = heading_idx + 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        para_parts: list[str] = []
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                break
            if line.strip().startswith("#"):
                break
            para_parts.append(line.strip())
            i += 1
        para = " ".join(para_parts).strip()
        if para:
            return para[:_SUMMARY_MAX_LEN]

    return text.strip()[:_SUMMARY_MAX_LEN]


def _extract_key_entities(page: dict[str, Any]) -> list[str]:
    """Best-effort entity names from page metadata; empty if unknown."""
    meta = page.get("metadata") or {}
    if not isinstance(meta, dict):
        return []
    raw = meta.get("key_entities")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if x is not None and str(x).strip()]


def has_parent_domains(state: dict[str, Any]) -> bool:
    """True if any top-level domain node has non-empty children (nested tree)."""
    domain_tree = state.get("domain_tree", []) or []
    for domain in domain_tree:
        children = domain.get("children", []) or []
        if children:
            return True
    return False


def _collect_parent_domains_by_level(
    domain_tree: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Collect parent domains (nodes with children) by depth; deepest level first."""
    levels: list[list[dict[str, Any]]] = []

    def _traverse(nodes: list[Any], depth: int) -> None:
        while len(levels) <= depth:
            levels.append([])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            children = node.get("children", []) or []
            if not isinstance(children, list):
                children = []
            if children:
                levels[depth].append(node)
                _traverse(children, depth + 1)

    if not isinstance(domain_tree, list):
        return []
    _traverse(domain_tree, 0)
    levels.reverse()
    return [lvl for lvl in levels if lvl]


def _build_subdomain_interactions(child_pages: list[dict[str, Any]]) -> str:
    """Build a text description of interactions between child sub-domains.

    Aggregates cross_domain_calls metadata from child page dicts into a
    structured summary for parent domain overview generation.
    """
    interactions: list[str] = []
    for page in child_pages:
        meta = page.get("metadata")
        if not isinstance(meta, dict):
            continue
        domain_name = meta.get("domain_name", page.get("title", ""))
        calls = meta.get("cross_domain_calls", [])
        if not isinstance(calls, list) or not calls:
            continue
        targets: dict[str, list[str]] = {}
        for call in calls:
            if not isinstance(call, dict):
                continue
            to_domain = call.get("to_domain", "")
            to_target = call.get("to", "")
            if to_domain:
                targets.setdefault(to_domain, []).append(to_target)
        for target_domain, callees in targets.items():
            unique_callees = list(dict.fromkeys(c for c in callees if c))[:3]
            callee_str = ", ".join(unique_callees) if unique_callees else "..."
            interactions.append(f"- {domain_name} → {target_domain}: {callee_str}")

    if not interactions:
        return ""
    return "## Sub-domain Interactions\n" + "\n".join(interactions[:20])


def _collect_module_names_in_subtree(domain: dict[str, Any]) -> list[str]:
    names: list[str] = []
    mods = domain.get("modules", []) or []
    if isinstance(mods, list):
        names.extend(str(m) for m in mods)
    for child in domain.get("children", []) or []:
        if isinstance(child, dict):
            names.extend(_collect_module_names_in_subtree(child))
    return names


def _module_dicts_for_names(
    module_names: list[str],
    modules_by_repo: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve module dicts from pipeline ``modules`` (first occurrence wins per name)."""
    index: dict[str, dict[str, Any]] = {}
    if isinstance(modules_by_repo, dict):
        for _repo, mod_list in modules_by_repo.items():
            if not isinstance(mod_list, list):
                continue
            for mod_dict in mod_list:
                if not isinstance(mod_dict, dict):
                    continue
                name = mod_dict.get("properties", {}).get("name", "")
                if name and name not in index:
                    index[name] = mod_dict
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mn in module_names:
        if mn in seen:
            continue
        m = index.get(mn)
        if m:
            out.append(m)
            seen.add(mn)
    return out


def _call_target_module(call: str) -> str | None:
    c = str(call).strip()
    if "." in c:
        return c.split(".", 1)[0]
    return None


def _build_page_data_for_semantic_diagrams(
    domain_name: str,
    module_names: list[str],
    module_index: dict[str, list[dict]],
) -> PageData:
    """Minimal PageData for SemanticDiagramGenerator (domain modules + CALLS edges)."""
    children: list[GraphNode] = []
    edges: list[GraphEdge] = []
    summaries: list[str] = []
    name_to_uid: dict[str, str] = {}

    for mod_name in module_names:
        for mod_dict in module_index.get(mod_name, []):
            props_raw = mod_dict.get("properties", {})
            props: dict[str, str | int | float | list[str]] = dict(props_raw) if isinstance(props_raw, dict) else {}
            uid = mod_dict.get("uid", f"Module::{mod_name}:0")
            name_to_uid[mod_name] = uid
            label_str = mod_dict.get("label", "Module")
            try:
                label = NodeLabel(label_str)
            except ValueError:
                label = NodeLabel.MODULE
            children.append(GraphNode(label=label, properties=props, uid=uid))
            bs = props.get("business_summary", "")
            if isinstance(bs, str) and bs.strip():
                summaries.append(bs)

    for mod_name in module_names:
        for mod_dict in module_index.get(mod_name, []):
            src_uid = mod_dict.get("uid", f"Module::{mod_name}:0")
            calls = mod_dict.get("properties", {}).get("calls", []) or []
            if not isinstance(calls, list):
                continue
            for call in calls:
                tgt_mod = _call_target_module(str(call))
                if not tgt_mod or tgt_mod not in name_to_uid:
                    continue
                tgt_uid = name_to_uid[tgt_mod]
                if tgt_uid == src_uid:
                    continue
                edges.append(
                    GraphEdge(
                        edge_type=EdgeType.CALLS,
                        source_uid=src_uid,
                        target_uid=tgt_uid,
                    )
                )

    joined_summary = " ".join(summaries)[:4000]
    center_props: dict[str, str | int | float | list[str]] = {
        "name": domain_name,
        "business_summary": joined_summary,
        "description": f"Business domain {domain_name}",
    }
    center = GraphNode(
        label=NodeLabel.MODULE,
        properties=center_props,
        uid=f"Domain::{domain_name}",
    )
    empty_loc = SourceLocation(
        file_path="", start_line=0, end_line=0, fqn=domain_name, repository=""
    )
    return PageData(
        node=center,
        edges=edges,
        children=children,
        source_location=empty_loc,
        method_locations=[],
        business_summary=joined_summary if joined_summary else None,
        methods=[],
    )


def _find_domain_in_tree(domain_tree: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Recursively find a domain node by name in the domain tree."""
    for domain in domain_tree:
        if domain.get("name") == name:
            return domain
        found = _find_domain_in_tree(domain.get("children", []) or [], name)
        if found is not None:
            return found
    return None


def _flatten_all_domains(domain_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return every domain node in the tree (including nested children), preorder."""
    nodes: list[dict[str, Any]] = []
    for domain in domain_tree:
        nodes.append(domain)
        nodes.extend(_flatten_all_domains(domain.get("children", []) or []))
    return nodes


def _count_modules_in_domain_tree(domain_tree: Any) -> int:
    """Sum module counts on every domain node at all nesting levels."""
    if not isinstance(domain_tree, list):
        return 0
    total = 0
    for d in domain_tree:
        if not isinstance(d, dict):
            continue
        mods = d.get("modules", []) or []
        total += len(mods)
        total += _count_modules_in_domain_tree(d.get("children", []) or [])
    return total
