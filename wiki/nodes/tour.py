"""Pipeline node: generate guided tour from page dependencies + architecture layers."""
from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.topo_sort import kahn_topological_order
from wiki.tour import GuidedTour, assign_page_layers, build_tour

log = get_logger(__name__)


def _is_tour_enabled() -> bool:
    try:
        from core.config import get_settings

        return get_settings().wiki.guided_tour_enabled
    except Exception:
        return True


def _build_page_dependency_graph(pages: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build page-level dependency graph from covered_entity_uids overlaps."""
    uid_to_page: dict[str, str] = {}
    for page in pages:
        path = page.get("path", "")
        for uid in page.get("covered_entity_uids") or []:
            uid_to_page[uid] = path

    edges: dict[str, list[str]] = {p.get("path", ""): [] for p in pages}
    page_paths = {p.get("path", "") for p in pages}

    for page in pages:
        path = page.get("path", "")
        if not path:
            continue
        deps = set()
        for uid in page.get("covered_entity_uids") or []:
            dep_page = uid_to_page.get(uid, "")
            if dep_page and dep_page != path and dep_page in page_paths:
                deps.add(dep_page)
        edges[path] = list(deps)

    return edges


async def generate_tour_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate guided tour from page dependencies + architecture layers."""
    if not _is_tour_enabled():
        return {"guided_tour": GuidedTour(total_pages=0).to_dict()}

    pages = state.get("pages") or []
    architecture_layers = state.get("architecture_layers") or {}

    if not pages:
        return {"guided_tour": GuidedTour(total_pages=0).to_dict()}

    page_deps = _build_page_dependency_graph(pages)
    topo_order = kahn_topological_order(page_deps)

    entity_to_module: dict[str, str] = {}
    for mod_name, info in architecture_layers.items():
        if isinstance(info, dict):
            for uid in info.get("entity_uids", []):
                entity_to_module[uid] = mod_name

    page_layers = assign_page_layers(pages, architecture_layers, entity_to_module)
    tour = build_tour(topo_order, page_layers, pages)

    log.info("tour_generated", total_pages=tour.total_pages, steps=len(tour.steps))
    return {"guided_tour": tour.to_dict()}
