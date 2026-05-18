"""Post-processing to merge small domains into larger siblings."""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

from core.log import get_logger

log = get_logger(__name__)


class DomainLike(Protocol):
    name: str
    modules: list


def _name_similarity(a: DomainLike, b: DomainLike) -> float:
    """Simple Jaccard similarity on module name character trigrams."""

    def trigrams(text: str) -> set[str]:
        t = text.lower()
        return {t[i : i + 3] for i in range(max(0, len(t) - 2))}

    a_tri = set()
    for m in a.modules:
        a_tri |= trigrams(str(m))
    b_tri = set()
    for m in b.modules:
        b_tri |= trigrams(str(m))

    if not a_tri or not b_tri:
        return 0.0
    return len(a_tri & b_tri) / len(a_tri | b_tri)


def merge_small_domains(domains: list, min_size: int = 3) -> list:
    """Merge domains with fewer than min_size modules into the most similar large domain."""
    large = [d for d in domains if len(d.modules) >= min_size]
    small = [d for d in domains if len(d.modules) < min_size]

    if not large and small:
        large = [small.pop(0)]

    for sd in small:
        if not large:
            break
        best = max(large, key=lambda ld: _name_similarity(sd, ld))
        best.modules.extend(sd.modules)
        if hasattr(sd, "children") and sd.children:
            if hasattr(best, "children"):
                best.children.extend(sd.children)
        log.info("domain_merged", small=sd.name, into=best.name, added=len(sd.modules))

    return large


def _tree_depth(nodes: list[dict]) -> int:
    if not nodes:
        return 0
    return 1 + max((_tree_depth(n.get("children", [])) for n in nodes), default=0)


def _parse_aggregation_result(
    response: str,
    nodes: list[dict],
) -> tuple[list[dict], dict[str, list[str]], list[str]]:
    """Parse LLM aggregation response.

    Returns:
        (new_groups, assign_to_existing, standalone_slugs)
    """
    valid_slugs = {n.get("name", "") for n in nodes}

    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.warning("aggregate_parse_failed", response_len=len(response))
        return [], {}, []

    new_groups: list[dict] = []
    for g in data.get("new_groups", []):
        children = [s for s in g.get("children_slugs", []) if s in valid_slugs]
        if len(children) >= 2:
            new_groups.append({
                "parent_display_name": g.get("parent_display_name", ""),
                "parent_slug": g.get("parent_slug", ""),
                "children_slugs": children,
            })

    assigns: dict[str, list[str]] = {}
    for parent_slug, children in data.get("assign_to_existing", {}).items():
        valid_children = [s for s in children if s in valid_slugs]
        if valid_children:
            assigns[parent_slug] = valid_children

    standalones = [s for s in data.get("standalone_slugs", []) if s in valid_slugs]

    return new_groups, assigns, standalones


def _apply_aggregation(
    nodes: list[dict],
    new_groups: list[dict],
    assign_to_existing: dict[str, list[str]],
) -> list[dict]:
    """Apply aggregation results: create parent nodes and assign orphans."""
    slug_to_node = {n.get("name", ""): n for n in nodes}
    used_slugs: set[str] = set()
    result: list[dict] = []

    existing_parents = {
        n.get("name", ""): n for n in nodes if n.get("children")
    }

    for assigns_parent, child_slugs in assign_to_existing.items():
        parent = existing_parents.get(assigns_parent)
        if parent:
            for cs in child_slugs:
                child = slug_to_node.get(cs)
                if child and cs not in used_slugs:
                    parent.setdefault("children", []).append(child)
                    used_slugs.add(cs)

    for group in new_groups:
        parent_slug = group["parent_slug"]
        children_slugs = group["children_slugs"]

        if parent_slug in existing_parents:
            parent = existing_parents[parent_slug]
            for cs in children_slugs:
                child = slug_to_node.get(cs)
                if child and cs not in used_slugs:
                    parent.setdefault("children", []).append(child)
                    used_slugs.add(cs)
        else:
            children = []
            for cs in children_slugs:
                child = slug_to_node.get(cs)
                if child and cs not in used_slugs:
                    children.append(child)
                    used_slugs.add(cs)
            if len(children) >= 2:
                from wiki.path_conventions import normalize_slug

                parent_node = {
                    "name": normalize_slug(parent_slug) or parent_slug,
                    "display_name": group["parent_display_name"],
                    "description": "",
                    "modules": [],
                    "children": children,
                }
                result.append(parent_node)

    for node in nodes:
        slug = node.get("name", "")
        if slug not in used_slugs:
            result.append(node)

    return result


def _build_aggregation_prompt(
    nodes: list[dict],
    existing_parents: list[dict],
) -> str:
    domain_info = [
        {
            "slug": d.get("name", ""),
            "display_name": d.get("display_name", ""),
            "description": d.get("description", ""),
            "module_count": len(d.get("modules", [])),
            "child_count": len(d.get("children", [])),
        }
        for d in nodes
    ]

    existing_section = ""
    if existing_parents:
        existing_section = (
            "\n已有父域结构（请优先将相关域归入已有父域，而非创建同名新组）：\n"
            + json.dumps(existing_parents, ensure_ascii=False, indent=2)
            + "\n"
        )

    return (
        f"以下是一个代码仓库中自动发现的 {len(nodes)} 个业务域。\n"
        "请分析这些域之间的语义关系，将属于同一业务主题的域分组到父域下。\n\n"
        "规则：\n"
        "1. 只有真正属于同一业务主题的域才应聚合\n"
        "   例如：\"家族核心管理\"、\"家族任务系统\"、\"家族战力\" → 父域 \"家族\"\n"
        "2. 不相关的域保持独立（标记为 standalone）\n"
        "3. 每个父域至少包含 2 个子域\n"
        "4. 父域名为简短的中文业务主题名\n"
        "5. 每个域只能属于一个组\n"
        "6. 不要过度聚合——只聚合明确相关的域\n"
        "7. 如果不确定某个域是否属于某组，标记为 standalone\n\n"
        f"{existing_section}\n"
        f"待分组的域列表：\n{json.dumps(domain_info, ensure_ascii=False, indent=2)}\n\n"
        "返回 JSON：\n"
        '{"new_groups": [{"parent_display_name": "家族", "parent_slug": "family", '
        '"children_slugs": ["family-core", "family-task"]}], '
        '"assign_to_existing": {"family": ["family-task"]}, '
        '"standalone_slugs": ["gift-order"]}\n'
        "其中 assign_to_existing 将域归入已有父域（key 为已有父域的 slug）。"
    )


_BATCH_SIZE = 25


async def aggregate_domains_recursive(
    nodes: list[dict],
    llm: Any,
    *,
    current_depth: int = 0,
    max_tree_depth: int = 5,
    min_siblings: int = 3,
) -> list[dict]:
    """Bottom-up recursive aggregation of semantically related domains."""
    if _tree_depth(nodes) >= max_tree_depth:
        return nodes

    for node in nodes:
        children = node.get("children", [])
        if children and len(children) >= min_siblings:
            node["children"] = await aggregate_domains_recursive(
                children,
                llm,
                current_depth=current_depth + 1,
                max_tree_depth=max_tree_depth,
                min_siblings=min_siblings,
            )

    if len(nodes) >= min_siblings:
        try:
            nodes = await _aggregate_siblings_by_theme(nodes, llm, max_tree_depth)
        except Exception:
            log.warning("aggregate_theme_failed", depth=current_depth, exc_info=True)

    return nodes


async def _aggregate_siblings_by_theme(
    nodes: list[dict],
    llm: Any,
    max_tree_depth: int,
) -> list[dict]:
    aggregable = [n for n in nodes if not n.get("user_modified")]

    if len(aggregable) < 3:
        return nodes

    existing_parents = [
        {
            "slug": n.get("name", ""),
            "display_name": n.get("display_name", ""),
            "children": [c.get("display_name", c.get("name", "")) for c in n.get("children", [])],
        }
        for n in nodes if n.get("children")
    ]

    if len(aggregable) <= _BATCH_SIZE:
        all_groups, all_assigns = await _single_aggregate_batch(
            aggregable, existing_parents, llm
        )
    else:
        all_groups, all_assigns = await _batched_aggregate(
            aggregable, existing_parents, llm
        )

    if not all_groups and not all_assigns:
        return nodes

    result = _apply_aggregation(nodes, all_groups, all_assigns)

    if _tree_depth(result) > max_tree_depth:
        log.info("aggregate_theme_skipped_depth", depth=_tree_depth(result), max=max_tree_depth)
        return nodes

    log.info("aggregate_theme_applied", groups=len(all_groups), assigns=len(all_assigns))
    return result


async def _single_aggregate_batch(
    nodes: list[dict],
    existing_parents: list[dict],
    llm: Any,
) -> tuple[list[dict], dict[str, list[str]]]:
    from wiki.prompts import SYSTEM_JSON_ONLY

    prompt = _build_aggregation_prompt(nodes, existing_parents)
    response = await llm.generate(prompt, system=SYSTEM_JSON_ONLY)
    groups, assigns, _ = _parse_aggregation_result(response, nodes)
    return groups, assigns


async def _batched_aggregate(
    nodes: list[dict],
    existing_parents: list[dict],
    llm: Any,
) -> tuple[list[dict], dict[str, list[str]]]:
    from wiki.prompts import SYSTEM_JSON_ONLY

    all_groups: list[dict] = []
    all_assigns: dict[str, list[str]] = {}
    all_standalones: list[dict] = []

    for i in range(0, len(nodes), _BATCH_SIZE):
        batch = nodes[i : i + _BATCH_SIZE]
        prompt = _build_aggregation_prompt(batch, existing_parents)
        try:
            response = await llm.generate(prompt, system=SYSTEM_JSON_ONLY)
            groups, assigns, standalone_slugs = _parse_aggregation_result(response, batch)
            all_groups.extend(groups)
            for k, v in assigns.items():
                all_assigns.setdefault(k, []).extend(v)
            standalone_nodes = [n for n in batch if n.get("name", "") in set(standalone_slugs)]
            all_standalones.extend(standalone_nodes)
        except Exception:
            log.warning("aggregate_batch_failed", batch_index=i, exc_info=True)
            all_standalones.extend(batch)

    if all_standalones and all_groups:
        consolidated_existing = existing_parents + [
            {"slug": g["parent_slug"], "display_name": g["parent_display_name"], "children": g["children_slugs"]}
            for g in all_groups
        ]
        try:
            prompt = _build_aggregation_prompt(all_standalones, consolidated_existing)
            response = await llm.generate(prompt, system=SYSTEM_JSON_ONLY)
            extra_groups, extra_assigns, _ = _parse_aggregation_result(response, all_standalones)
            all_groups.extend(extra_groups)
            for k, v in extra_assigns.items():
                all_assigns.setdefault(k, []).extend(v)
        except Exception:
            log.warning("aggregate_consolidation_failed", exc_info=True)

    return all_groups, all_assigns
