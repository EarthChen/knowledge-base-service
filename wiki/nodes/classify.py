"""Classification and domain hierarchy nodes."""

import re
from collections import Counter, defaultdict
from typing import Any

from core.config import get_settings
from core.log import get_logger
from store.schema import GraphNode, NodeLabel
from wiki.entity_role_classifier import EntityRoleClassifier, WikiEntityRole
from wiki.nodes.utils import _count_modules_in_domain_tree
from wiki.path_conventions import normalize_slug

log = get_logger(__name__)


def _split_pinned_module_key(key: str) -> tuple[str | None, str]:
    """Return ``(repo_id, module_name)`` for compound ``repo|name`` keys."""
    if "|" in key:
        repo, name = key.split("|", 1)
        if repo and name:
            return repo, name
    return None, key


def is_module_pinned(pinned_modules: dict[str, str], repo: str, name: str) -> bool:
    """True when ``repo|name`` or bare ``name`` is pinned."""
    if not pinned_modules:
        return False
    compound = f"{repo}|{name}"
    return compound in pinned_modules or name in pinned_modules


def get_pinned_domain_slug(pinned_modules: dict[str, str], repo: str, name: str) -> str | None:
    """Resolve target domain slug for a pinned module (compound key wins)."""
    if not pinned_modules:
        return None
    compound = f"{repo}|{name}"
    if compound in pinned_modules:
        return pinned_modules[compound]
    return pinned_modules.get(name)


_PREFIX_RE = re.compile(r"^([A-Z]{2,}(?=[A-Z][a-z])|[A-Z][a-z]+)")
_GENERIC_PREFIXES = frozenset({
    "User", "Base", "Abstract", "Default", "Common", "Generic",
    "Internal", "Simple", "Basic", "Custom", "Main", "Core",
    "Global", "Shared", "App", "Web", "Service", "Data",
    "Info", "Config", "Util", "Tool", "System",
})


def _extract_prefix(name: str) -> str | None:
    """Extract consolidation prefix from module name."""
    if "_" in name:
        first = name.split("_")[0]
        if len(first) >= 2:
            return first[0].upper() + first[1:]
        return None
    m = _PREFIX_RE.match(name)
    if m:
        prefix = m.group(1)
        return prefix if prefix not in _GENERIC_PREFIXES else None
    return None


def _ensure_ascii_keys(
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
) -> tuple[dict[str, list], dict[str, str]]:
    """Normalize domain_mapping keys to ASCII slugs.

    Non-ASCII keys (e.g. Chinese names) are replaced with normalize_slug output
    or an indexed fallback. Original names are preserved in domain_display_names.
    """
    result: dict[str, list] = {}
    updated_display = dict(domain_display_names)
    unnamed_counter = 0

    for key, pairs in domain_mapping.items():
        if key.isascii() and key.strip():
            result[key] = pairs
            continue
        ascii_slug = normalize_slug(key)
        if not ascii_slug or ascii_slug == "unnamed" or ascii_slug in result:
            unnamed_counter += 1
            ascii_slug = f"domain-{unnamed_counter:02d}"
        updated_display.setdefault(ascii_slug, key)
        result[ascii_slug] = pairs

    if result != domain_mapping:
        log.info(
            "domain_keys_normalized",
            original_count=len(domain_mapping),
            normalized_count=len(result),
        )
    return result, updated_display


def _compound_module_key(repo: str, name: str) -> str:
    return f"{repo}|{name}"


def _reconcile_tree_with_mapping(
    tree: list[dict[str, Any]],
    domain_mapping: dict[str, list[tuple[str, str]]],
) -> None:
    """Ensure every module in the tree is placed under the correct domain per domain_mapping.

    Tree modules may be compound keys (``repo|name``) or bare names for legacy trees.
    Mapping always uses ``(repo, name)`` pairs; compound keys disambiguate cross-repo
    same-name modules.
    """
    module_to_mapping_slug: dict[str, str] = {}
    bare_name_repos: dict[str, set[str]] = defaultdict(set)
    for slug, pairs in domain_mapping.items():
        for repo, mod_name in pairs:
            compound = _compound_module_key(repo, mod_name)
            module_to_mapping_slug[compound] = slug
            bare_name_repos[mod_name].add(repo)

    for mod_name, repos in bare_name_repos.items():
        if len(repos) == 1:
            repo = next(iter(repos))
            module_to_mapping_slug[mod_name] = module_to_mapping_slug[_compound_module_key(repo, mod_name)]

    slug_to_node: dict[str, dict[str, Any]] = {}

    def _index_nodes(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            slug = node.get("name", "")
            if slug:
                slug_to_node[slug] = node
            _index_nodes(node.get("children", []))

    _index_nodes(tree)

    modules_in_tree: set[str] = set()

    def _lookup_mapping_slug(mod: str) -> str | None:
        repo, name = _split_pinned_module_key(mod)
        if repo:
            return module_to_mapping_slug.get(mod) or module_to_mapping_slug.get(_compound_module_key(repo, name))
        return module_to_mapping_slug.get(name)

    def _collect_and_filter(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            slug = node.get("name", "")
            kept: list[str] = []
            for mod in node.get("modules", []):
                mapping_slug = _lookup_mapping_slug(mod)
                if mapping_slug is None or mapping_slug == slug:
                    kept.append(mod)
                    modules_in_tree.add(mod)
                elif mapping_slug in slug_to_node:
                    target = slug_to_node[mapping_slug]
                    target_modules = target.setdefault("modules", [])
                    if mod not in target_modules:
                        target_modules.append(mod)
                    modules_in_tree.add(mod)
            node["modules"] = kept
            _collect_and_filter(node.get("children", []))

    _collect_and_filter(tree)

    for slug, pairs in domain_mapping.items():
        if slug not in slug_to_node:
            node: dict[str, Any] = {
                "name": slug,
                "display_name": slug,
                "modules": [],
                "children": [],
            }
            tree.append(node)
            slug_to_node[slug] = node

        target = slug_to_node[slug]
        target_modules = target.setdefault("modules", [])
        for repo, mod_name in pairs:
            compound = _compound_module_key(repo, mod_name)
            already_present = compound in modules_in_tree
            if not already_present and len(bare_name_repos.get(mod_name, set())) == 1:
                already_present = mod_name in modules_in_tree
            if not already_present:
                target_modules.append(compound)
                modules_in_tree.add(compound)


def _consolidate_split_entities(
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
    """Merge modules with the same business-entity prefix into one domain.

    When LLM splits Family*, Intimacy* etc. across multiple domains, this
    heuristic consolidates them: for each entity prefix that appears in 3+
    modules, find the domain that owns the majority and move the rest there.
    """
    cfg = get_settings().wiki

    module_to_domain: dict[tuple[str, str], str] = {}
    for slug, pairs in domain_mapping.items():
        for repo, mod_name in pairs:
            module_to_domain[(repo, mod_name)] = slug

    prefix_modules: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for repo, mod_name in module_to_domain:
        prefix = _extract_prefix(mod_name)
        if prefix:
            prefix_modules[(repo, prefix)].append((repo, mod_name))

    moves: dict[tuple[str, str], str] = {}
    for (_repo, _prefix), mod_keys in prefix_modules.items():
        if len(mod_keys) < cfg.consolidation_min_count:
            continue
        domain_counts: Counter[str] = Counter()
        for key in mod_keys:
            domain_counts[module_to_domain[key]] += 1
        if len(domain_counts) < cfg.consolidation_min_domains:
            continue
        majority_domain = domain_counts.most_common(1)[0][0]
        for key in mod_keys:
            current = module_to_domain[key]
            if current != majority_domain:
                moves[key] = majority_domain

    if not moves:
        return domain_mapping, domain_display_names

    new_mapping: dict[str, list[tuple[str, str]]] = {}
    for slug, pairs in domain_mapping.items():
        kept = [(r, m) for r, m in pairs if moves.get((r, m), slug) == slug]
        new_mapping[slug] = kept
    for (repo, mod_name), target_slug in moves.items():
        new_mapping.setdefault(target_slug, []).append((repo, mod_name))

    new_mapping = {k: v for k, v in new_mapping.items() if v}

    log.info("consolidate_split_entities", moved=len(moves))
    return new_mapping, domain_display_names


async def classify_entities_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 1: classify all entities using EntityRoleClassifier."""
    classifier = EntityRoleClassifier()
    entity_roles: dict[str, WikiEntityRole] = {}
    role_counter: Counter[WikiEntityRole] = Counter()

    for _repo, modules in state.get("modules", {}).items():
        for mod_dict in modules:
            uid = mod_dict.get("uid", "")
            props = mod_dict.get("properties", {})
            label_str = mod_dict.get("label", "Module")
            try:
                label = NodeLabel(label_str)
            except ValueError:
                label = NodeLabel.MODULE
            node = GraphNode(label=label, properties=props, uid=uid)

            calls = props.get("calls", []) or []
            imports = props.get("imports", []) or []
            if isinstance(calls, list) and isinstance(imports, list):
                edge_count = len(calls) + len(imports)
            else:
                edge_count = 0

            children_count = int(props.get("inner_class_count", 0) or 0)

            role = classifier.classify(node, edge_count=edge_count, children_count=children_count)
            entity_roles[uid] = role
            role_counter[role] += 1

    log.info(
        "classify_entities_done",
        total=len(entity_roles),
        **{str(r): c for r, c in role_counter.items()},
    )
    return {
        "entity_roles": entity_roles,
        "role_stats": {str(r): c for r, c in role_counter.items()},
    }


async def detect_reorg_node(state: dict[str, Any]) -> dict[str, Any]:
    """Determine reorganization type based on pipeline state.

    Returns reorg_type: first_run | full | heavy | medium | light | none
    """
    domain_tree = state.get("domain_tree")
    is_incremental = state.get("is_incremental", False)
    affected_domains = state.get("affected_domains", [])

    if domain_tree is None:
        reorg_type = "first_run"
    elif not is_incremental:
        reorg_type = "full"
    elif affected_domains:
        affected_modules = state.get("affected_modules") or set()
        prev_biz = _count_modules_in_domain_tree(
            domain_tree if isinstance(domain_tree, list) else []
        )
        if prev_biz == 0:
            reorg_type = "heavy"
        else:
            cfg = state.get("config") or {}
            light_threshold = float(cfg.get("reorg_light_threshold", 0.1))
            heavy_threshold = float(cfg.get("reorg_heavy_threshold", 0.3))
            ratio = len(affected_modules) / max(prev_biz, 1)
            if ratio <= light_threshold:
                reorg_type = "light"
            elif ratio <= heavy_threshold:
                reorg_type = "medium"
            else:
                reorg_type = "heavy"
    else:
        reorg_type = "none"

    log.info("detect_reorg_done", reorg_type=reorg_type, is_incremental=is_incremental)
    return {"reorg_type": reorg_type}


async def set_review_status_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark domain tree as pending_review and continue (non-blocking)."""
    review_status = dict(state.get("review_status", {}))
    review_status["domain_tree"] = "pending_review"

    log.info("set_review_status_marked_review", tree_size=len(state.get("domain_tree") or []))
    return {"review_status": review_status}
