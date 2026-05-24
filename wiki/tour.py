"""Guided tour data model and builder utilities."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

LAYER_PRIORITY = {"api": 1, "service": 2, "data": 3, "infrastructure": 4, "unknown": 5}
LAYER_DISPLAY = {
    "api": "API 入口层",
    "service": "业务服务层",
    "data": "数据访问层",
    "infrastructure": "基础设施层",
    "unknown": "其他",
}


@dataclass
class TourPage:
    path: str
    title: str
    reading_order: int
    architecture_layer: str


@dataclass
class TourStep:
    order: int
    layer_name: str
    layer_display: str
    pages: list[TourPage] = field(default_factory=list)


@dataclass
class GuidedTour:
    total_pages: int
    steps: list[TourStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_pages": self.total_pages,
            "steps": [
                {
                    "order": s.order,
                    "layer_name": s.layer_name,
                    "layer_display": s.layer_display,
                    "pages": [asdict(p) for p in s.pages],
                }
                for s in self.steps
            ],
        }


def assign_page_layers(
    pages: list[dict[str, Any]],
    architecture_layers: dict[str, dict[str, Any]],
    entity_to_module: dict[str, str],
) -> dict[str, str]:
    """Assign architecture layer to each page via majority vote of its covered entities' modules."""
    result: dict[str, str] = {}
    for page in pages:
        path = page.get("path", "")
        entity_uids = page.get("covered_entity_uids") or []
        layer_votes: list[str] = []
        for uid in entity_uids:
            module = entity_to_module.get(uid, "")
            if module and module in architecture_layers:
                layer_votes.append(architecture_layers[module].get("layer", "unknown"))
        if layer_votes:
            result[path] = Counter(layer_votes).most_common(1)[0][0]
        else:
            result[path] = "unknown"
    return result


def build_tour(
    topo_order: list[str],
    page_layers: dict[str, str],
    pages: list[dict[str, Any]],
) -> GuidedTour:
    """Build a GuidedTour from topological order + layer assignments."""
    if not topo_order:
        return GuidedTour(total_pages=0, steps=[])

    title_map = {p.get("path", ""): p.get("title", p.get("path", "")) for p in pages}

    layer_pages: dict[str, list[TourPage]] = {}
    reading_order = 0
    for path in topo_order:
        layer = page_layers.get(path, "unknown")
        reading_order += 1
        tp = TourPage(
            path=path,
            title=title_map.get(path, path),
            reading_order=reading_order,
            architecture_layer=layer,
        )
        layer_pages.setdefault(layer, []).append(tp)

    steps: list[TourStep] = []
    step_order = 0
    for layer_name in sorted(layer_pages.keys(), key=lambda layer: LAYER_PRIORITY.get(layer, 99)):
        step_order += 1
        steps.append(
            TourStep(
                order=step_order,
                layer_name=layer_name,
                layer_display=LAYER_DISPLAY.get(layer_name, layer_name),
                pages=layer_pages[layer_name],
            )
        )

    return GuidedTour(total_pages=reading_order, steps=steps)
