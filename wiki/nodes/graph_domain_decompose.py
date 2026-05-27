"""Graph-driven domain decomposition node for wiki pipeline."""

import asyncio
import hashlib
import re
from typing import Any

import numpy as np
from langchain_core.runnables import RunnableConfig

from core.config import get_settings
from core.log import get_logger
from wiki.domain_semantic_clusterer import DomainSemanticClusterer
from wiki.entity_role_classifier import DOMAIN_CLASSIFICATION_ENTITY_ROLES, WikiEntityRole
from wiki.graph_call_query import fetch_module_call_edges
from wiki.graph_domain_namer import GraphDomainNamer
from wiki.graph_semantic_corrector import GraphSemanticCorrector
from wiki.llm_rate_limiter import acquire_llm_quota
from wiki.nodes.classify import (
    _consolidate_split_entities,
    _ensure_ascii_keys,
    _split_pinned_module_key,
    is_module_pinned,
)
from wiki.nodes.domain_filters import is_data_model
from wiki.path_conventions import normalize_slug, normalize_slug_strict
from wiki.pipeline_concurrency import PipelineConcurrency

log = get_logger(__name__)


def _compound_key(repo: str, name: str) -> str:
    return f"{repo}|{name}"


def _lookup_module_value(mapping: dict[str, Any], repo: str, name: str) -> Any:
    """Resolve module-scoped dict value by compound key, falling back to bare name."""
    return mapping.get(_compound_key(repo, name), mapping.get(name))


def _build_module_summaries_flat_for_corrector(
    biz_modules: list[tuple[str, str]],
    module_summaries_raw: dict[str, Any],
) -> dict[str, str]:
    """Flatten module summaries for GraphSemanticCorrector, keyed by compound key."""
    name_counts: dict[str, int] = {}
    for _, mod_name in biz_modules:
        name_counts[mod_name] = name_counts.get(mod_name, 0) + 1

    module_summaries_flat: dict[str, str] = {}
    for repo_id, mod_name in biz_modules:
        data = _lookup_module_value(module_summaries_raw, repo_id, mod_name)
        compound = _compound_key(repo_id, mod_name)
        summary_text = ""
        if isinstance(data, dict):
            summary_text = str(data.get("summary_text", ""))
        elif isinstance(data, str):
            summary_text = data
        module_summaries_flat[compound] = summary_text
        if name_counts[mod_name] == 1:
            module_summaries_flat[mod_name] = summary_text
    return module_summaries_flat


def _build_paths_for_corrector(
    biz_modules: list[tuple[str, str]],
    module_paths: dict[str, str],
) -> dict[str, str]:
    """Build module path lookup for GraphSemanticCorrector, keyed by compound key."""
    name_counts: dict[str, int] = {}
    for _, mod_name in biz_modules:
        name_counts[mod_name] = name_counts.get(mod_name, 0) + 1

    paths_for_corrector: dict[str, str] = {}
    for repo_id, mod_name in biz_modules:
        compound = _compound_key(repo_id, mod_name)
        path = module_paths.get(compound, module_paths.get(mod_name, ""))
        paths_for_corrector[compound] = path
        if name_counts[mod_name] == 1:
            paths_for_corrector[mod_name] = path
    return paths_for_corrector


def _resolve_content_language(state: dict[str, Any]) -> str:
    cfg = state.get("config") or {}
    nested = cfg.get("config") or {}
    return (
        state.get("language")
        or cfg.get("language")
        or nested.get("language")
        or get_settings().wiki.wiki_content_language
    )


def _embedding_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _embed_texts_with_cache(
    texts: list[str],
    cache: dict[str, list[float]],
    generator: Any,
) -> list[list[float]]:
    """Generate embeddings, reusing entries in *cache* keyed by text SHA-256."""
    result: list[list[float] | None] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []
    for i, text in enumerate(texts):
        key = _embedding_text_hash(text)
        if key in cache:
            result[i] = cache[key]
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)
    if uncached_texts:
        new_embeddings = await generator.generate(uncached_texts)
        for idx, text, emb in zip(uncached_indices, uncached_texts, new_embeddings, strict=True):
            cache[_embedding_text_hash(text)] = emb
            result[idx] = emb
    return [emb for emb in result if emb is not None]


def _apply_merge_map(
    merge_map: dict[str, str],
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
) -> tuple[dict[str, list], dict[str, str]]:
    """Apply a slug→target merge map to domain mapping and display names."""
    if not merge_map:
        return domain_mapping, domain_display_names

    new_mapping: dict[str, list] = {}
    new_display: dict[str, str] = {}
    for domain, modules in domain_mapping.items():
        actual = merge_map.get(domain, domain)
        new_mapping.setdefault(actual, []).extend(modules)
        if actual not in new_display and actual in domain_display_names:
            new_display[actual] = domain_display_names[actual]

    for d, display in domain_display_names.items():
        if d not in merge_map and d not in new_display:
            new_display[d] = display

    return new_mapping, new_display


_HASH_SUFFIX_RE = re.compile(r"^(.+)-([0-9a-f]{4})$")
_NUMERIC_SUFFIX_RE = re.compile(r"^(.+)-(\d{1,2})$")


def _cleanup_collision_slugs(
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
) -> tuple[dict[str, list], dict[str, str]]:
    """Merge domains with hash (-xxxx) or numeric (-N) suffixes into their base slug."""
    merge_map: dict[str, str] = {}
    all_slugs = set(domain_mapping.keys())

    for slug in sorted(all_slugs):
        m = _HASH_SUFFIX_RE.match(slug)
        if m:
            base = m.group(1)
            if base in all_slugs or base != slug:
                merge_map[slug] = base
            continue

        m = _NUMERIC_SUFFIX_RE.match(slug)
        if m:
            base = m.group(1)
            suffix_num = int(m.group(2))
            if suffix_num <= 20 and (
                base in all_slugs
                or any(
                    _NUMERIC_SUFFIX_RE.match(s) and _NUMERIC_SUFFIX_RE.match(s).group(1) == base
                    for s in all_slugs
                    if s != slug
                )
            ):
                merge_map[slug] = base

    if not merge_map:
        return domain_mapping, domain_display_names

    log.info(
        "collision_slug_cleanup",
        merged_count=len(merge_map),
        merge_map=merge_map,
    )
    return _apply_merge_map(merge_map, domain_mapping, domain_display_names)


_PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]+$")
_INFRA_CLASS_SUFFIXES = (
    "Impl",
    "Configuration",
    "Config",
    "TypeHandler",
    "Aspect",
    "Interceptor",
    "Filter",
    "Wrapper",
    "Handler",
    "Executor",
)


def _is_infra_slug(
    slug: str,
    modules: list[tuple[str, str]],
    infrastructure_keywords: list[str],
) -> bool:
    """Return True if slug/modules match infrastructure domain heuristics."""
    if len(modules) == 1:
        _, name = modules[0]
        if _PASCAL_CASE_RE.match(name) and name.endswith(_INFRA_CLASS_SUFFIXES):
            return True
    if len(modules) <= 3 and infrastructure_keywords:
        slug_lower = slug.lower()
        if any(kw in slug_lower for kw in infrastructure_keywords):
            return True
    return False


def _filter_infra_sub_domains(
    named_subs: list[dict],
    infrastructure_keywords: list[str],
) -> list[dict]:
    """Remove infrastructure sub-domains; merge their modules into the largest sibling."""
    if not named_subs:
        return named_subs

    for sub in named_subs:
        children = sub.get("children") or []
        if children:
            sub["children"] = _filter_infra_sub_domains(children, infrastructure_keywords)

    infra_subs: list[dict] = []
    remaining: list[dict] = []
    for sub in named_subs:
        modules = sub.get("modules", [])
        if _is_infra_slug(sub.get("slug", ""), modules, infrastructure_keywords):
            infra_subs.append(sub)
        else:
            remaining.append(sub)

    if not infra_subs:
        return named_subs
    if not remaining:
        return named_subs

    largest = max(remaining, key=lambda s: len(s.get("modules", [])))
    for sub in infra_subs:
        largest["modules"].extend(sub.get("modules", []))

    return remaining


def _filter_infrastructure_domains(
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
    infrastructure_keywords: list[str],
    edges: list[tuple[tuple[str, str], tuple[str, str], int]] | None = None,
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
    """Filter infrastructure domains by merging into call-graph neighbors or largest domain.

    Rules:
    1. Single-module domain where module name is PascalCase and ends with a known
       infrastructure class suffix → infrastructure
    2. Slug contains any infrastructure keyword AND module count ≤ 3 → infrastructure

    Merge target: non-infra domain with most call edges to/from infra modules; if none,
    fall back to the largest remaining domain.
    """
    if not domain_mapping:
        return domain_mapping, domain_display_names

    infra_slugs: set[str] = set()
    for slug, modules in domain_mapping.items():
        if _is_infra_slug(slug, modules, infrastructure_keywords):
            infra_slugs.add(slug)

    if not infra_slugs:
        return domain_mapping, domain_display_names

    remaining = {s: list(m) for s, m in domain_mapping.items() if s not in infra_slugs}
    if not remaining:
        return domain_mapping, domain_display_names

    module_to_domain: dict[tuple[str, str], str] = {}
    for slug, modules in remaining.items():
        for mod in modules:
            module_to_domain[mod] = slug

    largest_slug = max(remaining, key=lambda s: len(remaining[s]))

    for slug in infra_slugs:
        infra_modules = set(domain_mapping[slug])
        if edges:
            domain_edge_count: dict[str, int] = {}
            for src, tgt, weight in edges:
                if src in infra_modules and tgt in module_to_domain:
                    target_domain = module_to_domain[tgt]
                    domain_edge_count[target_domain] = domain_edge_count.get(target_domain, 0) + weight
                elif tgt in infra_modules and src in module_to_domain:
                    source_domain = module_to_domain[src]
                    domain_edge_count[source_domain] = domain_edge_count.get(source_domain, 0) + weight

            if domain_edge_count:
                best_domain = max(domain_edge_count, key=domain_edge_count.get)
                remaining[best_domain].extend(domain_mapping[slug])
                continue

        remaining[largest_slug].extend(domain_mapping[slug])

    remaining_names = {s: n for s, n in domain_display_names.items() if s not in infra_slugs}
    return remaining, remaining_names


def _enforce_domain_budget(
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
    budget: int = 50,
) -> tuple[dict[str, list], dict[str, str]]:
    """Merge smallest domains until total count <= budget."""
    if len(domain_mapping) <= budget:
        return domain_mapping, domain_display_names

    working = dict(domain_mapping)
    display = dict(domain_display_names)

    while len(working) > budget:
        sorted_slugs = sorted(working.keys(), key=lambda s: len(working[s]))
        smallest = sorted_slugs[0]
        next_smallest = sorted_slugs[1] if len(sorted_slugs) > 1 else None
        if next_smallest is None:
            break
        working[next_smallest] = working[next_smallest] + working.pop(smallest)
        display.pop(smallest, None)

    log.info("domain_budget_enforced", original=len(domain_mapping), final=len(working), budget=budget)
    return working, display


async def _merge_domains_by_embedding(
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
    similarity_threshold: float | None = None,
    embedding_cache: dict[str, list[float]] | None = None,
) -> tuple[dict[str, list], dict[str, str]]:
    """Fallback: merge domains whose display_name embeddings exceed similarity threshold."""
    from numpy import dot
    from numpy.linalg import norm

    from core.config import get_settings
    from indexer.embedding_generator import EmbeddingGenerator

    if similarity_threshold is None:
        similarity_threshold = get_settings().wiki.embedding_merge_threshold

    slugs = list(domain_display_names.keys())
    names = [domain_display_names[s] for s in slugs]
    if len(names) <= 2:
        return domain_mapping, domain_display_names

    cache = embedding_cache if embedding_cache is not None else {}
    try:
        config = get_settings().embedding
        generator = EmbeddingGenerator.shared(config)
        embeddings = await _embed_texts_with_cache(names, cache, generator)
    except Exception:
        log.warning("embedding_domain_merge_failed", exc_info=True)
        return domain_mapping, domain_display_names

    merge_map: dict[str, str] = {}
    merged_targets: set[str] = set()
    for i in range(len(slugs)):
        if slugs[i] in merge_map:
            continue
        for j in range(i + 1, len(slugs)):
            if slugs[j] in merge_map or slugs[j] in merged_targets:
                continue
            norm_i, norm_j = norm(embeddings[i]), norm(embeddings[j])
            if norm_i == 0 or norm_j == 0:
                continue
            sim = dot(embeddings[i], embeddings[j]) / (norm_i * norm_j)
            if sim >= similarity_threshold:
                size_i = len(domain_mapping.get(slugs[i], []))
                size_j = len(domain_mapping.get(slugs[j], []))
                if size_i >= size_j:
                    target, source = slugs[i], slugs[j]
                else:
                    target, source = slugs[j], slugs[i]
                if len(domain_mapping.get(source, [])) <= 40:
                    merge_map[source] = target
                    merged_targets.add(target)

    if not merge_map:
        return domain_mapping, domain_display_names

    log.info("merge_domains_by_embedding", merged=len(merge_map), targets=list(set(merge_map.values())))
    return _apply_merge_map(merge_map, domain_mapping, domain_display_names)


async def _merge_domains_by_llm(
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
    llm,
) -> tuple[dict[str, list], dict[str, str]]:
    """Use LLM to discover which domains should be merged based on semantic similarity."""
    if len(domain_mapping) <= 2:
        return domain_mapping, domain_display_names

    domain_infos = []
    for slug, modules in domain_mapping.items():
        display = domain_display_names.get(slug, slug)
        sample_names = sorted({name for _, name in modules})[:8]
        domain_infos.append(f"- {slug} ({display}): {', '.join(sample_names)}")

    prompt = (
        "Given these business domains and their module samples, "
        "identify which domains should be merged because they represent "
        "the same business concept from different angles.\n\n"
        + "\n".join(domain_infos)
        + f"\n\nCurrent domain count: {len(domain_mapping)}. "
        "Target 8-15 domains total. If the count is significantly above 15, "
        "be more aggressive with merging. Each merged domain should have >= 3 modules.\n\n"
        "Return JSON: {\"merge_groups\": [[\"slugA\", \"slugB\"], ...]}. "
        "Only include groups that should definitely be merged. "
        "Return {\"merge_groups\": []} if no merges are needed."
    )
    messages = [{"role": "user", "content": prompt}]

    merge_groups: list[list[str]] = []
    if not hasattr(llm, "complete_json"):
        log.warning("llm_no_complete_json_method", provider=type(llm).__name__)
        try:
            return await _merge_domains_by_embedding(domain_mapping, domain_display_names)
        except Exception:
            log.warning("embedding_domain_merge_fallback_failed", exc_info=True)
            return domain_mapping, domain_display_names

    try:
        from wiki.llm_schemas import DomainMergeOutput

        result = await llm.complete_json(messages, DomainMergeOutput.model_json_schema())
        if isinstance(result, dict):
            raw_groups = result.get("merge_groups", [])
            if isinstance(raw_groups, list):
                merge_groups = raw_groups
    except Exception:
        log.warning("llm_domain_merge_failed", exc_info=True)
        try:
            return await _merge_domains_by_embedding(domain_mapping, domain_display_names)
        except Exception:
            log.warning("embedding_domain_merge_fallback_failed", exc_info=True)
            return domain_mapping, domain_display_names

    merge_map: dict[str, str] = {}
    for group in merge_groups:
        if not isinstance(group, list):
            continue
        valid = [s for s in group if s in domain_mapping]
        if len(valid) <= 1:
            continue
        target = max(valid, key=lambda s: len(domain_mapping.get(s, [])))
        for s in valid:
            if s != target and len(domain_mapping.get(s, [])) <= 40:
                merge_map[s] = target

    if not merge_map:
        return domain_mapping, domain_display_names

    log.info("merge_domains_by_llm", merged=len(merge_map), targets=list(set(merge_map.values())))
    return _apply_merge_map(merge_map, domain_mapping, domain_display_names)


_SPLIT_THRESHOLD = 10
_MAX_SPLIT_DEPTH = 2


def _get_split_params() -> tuple[int, int]:
    cfg = get_settings().wiki
    threshold = getattr(cfg, "domain_split_threshold", None)
    max_depth = getattr(cfg, "domain_split_max_depth", None)
    return (
        threshold if isinstance(threshold, int) else _SPLIT_THRESHOLD,
        max_depth if isinstance(max_depth, int) else _MAX_SPLIT_DEPTH,
    )


def _sub_tree_node_name(sub: dict, *, idx: int = 0) -> str:
    """Resolve ASCII slug for a sub-domain tree node."""
    name = (
        normalize_slug_strict(sub.get("slug", ""))
        or normalize_slug_strict(sub.get("display_name", ""))
    )
    if name:
        return name
    modules = sub.get("modules", [])
    if modules:
        short_names = [
            (name if isinstance(name, str) else str(name)).rsplit(".", 1)[-1][:12]
            for _repo, name in modules[:2]
        ]
        name = normalize_slug_strict("-".join(short_names))
        if name:
            return name
    return f"sub-domain-{idx}"


def _sub_to_tree_node(sub: dict, *, idx: int = 0) -> dict[str, Any]:
    """Convert a recursive sub-domain dict into a domain_tree node."""
    children_raw = sub.get("children", [])
    children = [_sub_to_tree_node(c, idx=i) for i, c in enumerate(children_raw)]
    node_name = _sub_tree_node_name(sub, idx=idx)
    if children:
        return {
            "name": node_name,
            "display_name": sub.get("display_name", ""),
            "modules": [],
            "children": children,
        }
    mod_keys = [_compound_key(repo, name) for repo, name in sub.get("modules", [])]
    return {
        "name": node_name,
        "display_name": sub.get("display_name", ""),
        "modules": mod_keys,
        "children": [],
    }


def _build_domain_tree(
    communities_named: list[dict],
    sub_trees: dict[str, list[dict]],
) -> list[dict[str, Any]]:
    """Build domain_tree from named communities and their sub-trees.

    communities_named: [{"slug": "...", "display_name": "...", "modules": [(repo, name), ...]}]
    sub_trees: slug -> list of sub-domain dicts (may contain nested children)
    """
    tree = []
    for community in communities_named:
        slug = community["slug"]
        display_name = community["display_name"]
        modules = community["modules"]

        sub = sub_trees.get(slug, [])
        if sub and len(sub) > 1:
            children = [_sub_to_tree_node(s, idx=i) for i, s in enumerate(sub)]
            tree.append({
                "name": slug,
                "display_name": display_name,
                "modules": [],
                "children": children,
            })
        else:
            mod_keys = [_compound_key(repo, name) for repo, name in modules]
            tree.append({
                "name": slug,
                "display_name": display_name,
                "modules": mod_keys,
                "children": [],
            })
    return tree


def _collapse_empty_shells(tree: list[dict]) -> list[dict]:
    """Collapse empty shell domains (0 modules, 1 child) bottom-up."""

    def _collapse_node(node: dict) -> dict:
        if node.get("children"):
            node["children"] = [_collapse_node(c) for c in node["children"]]

        modules = node.get("modules") or []
        children = node.get("children") or []
        if not modules and len(children) == 1:
            child = children[0]
            collapsed_from = list(child.get("collapsed_from", []))
            collapsed_from.append(node.get("name", ""))
            child["collapsed_from"] = collapsed_from
            return child
        return node

    return [_collapse_node(n) for n in tree]


_GENERIC_DIFFERENTIATORS = frozenset({
    "核心",
    "模块",
    "管理",
    "服务",
    "系统",
    "core",
    "module",
    "management",
    "service",
    "system",
})

_PARENT_CHILD_SLUG_MISMATCHES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("intimacy", "relation", "亲密"), ("user-behavior", "behavior-stat", "用户行为")),
]


def _extract_differentiator(description: str) -> str:
    """Extract a short label from description for display-name disambiguation."""
    text = description.strip()
    if not text:
        return ""
    for part in re.findall(r"[\u4e00-\u9fff]{2,4}", text):
        if part not in _GENERIC_DIFFERENTIATORS:
            return part[:4]
    for part in re.findall(r"[A-Za-z]{3,}", text):
        if part.lower() not in _GENERIC_DIFFERENTIATORS:
            return part[:12]
    cn_parts = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    return cn_parts[0][:4] if cn_parts else ""


def _slug_semantically_mismatched(parent_slug: str, child_slug: str) -> bool:
    """Heuristic: child slug themes that clash with parent slug themes."""
    parent_l = parent_slug.lower()
    child_l = child_slug.lower()
    for parent_tokens, child_tokens in _PARENT_CHILD_SLUG_MISMATCHES:
        parent_hit = any(tok in parent_l for tok in parent_tokens)
        child_hit = any(tok in child_l for tok in child_tokens)
        if parent_hit and child_hit:
            return True
    return False


def _review_subdomain_placement(
    domain_tree: list[dict],
    embeddings: dict[str, list[float]] | None = None,
) -> list[dict[str, str]]:
    """Review sub-domain placement for semantic mismatches. Returns warnings (detection only)."""
    del embeddings  # reserved for future embedding-based checks
    warnings: list[dict[str, str]] = []

    def _walk(nodes: list[dict]) -> None:
        for node in nodes:
            children = node.get("children", [])
            if not children:
                continue
            parent_slug = node.get("name", "")
            parent_display = node.get("display_name", "")
            for child in children:
                child_slug = child.get("name", "")
                child_display = child.get("display_name", "")
                if _slug_semantically_mismatched(parent_slug, child_slug):
                    warnings.append({
                        "child": child_slug,
                        "parent": parent_slug,
                        "reason": (
                            f"'{child_display}' semantically mismatched with parent '{parent_display}'"
                        ),
                    })
            _walk(children)

    _walk(domain_tree)
    for warning in warnings:
        log.warning("subdomain_placement_mismatch", **warning)
    return warnings


def _dedup_parallel_naming_results(
    results: list[dict],
    existing_slugs: list[str],
) -> list[dict]:
    """Deduplicate slugs after parallel LLM naming."""
    seen: set[str] = set(existing_slugs)
    for result in results:
        slug = result["slug"]
        if slug in seen:
            modules = result.get("modules", [])
            suffix = ""
            if modules:
                short_names = [str(m).rsplit(".", 1)[-1][:12] for m in modules[:2]]
                suffix = normalize_slug("-".join(short_names))
            if not suffix or suffix == "unnamed":
                counter = 2
                while f"{slug}-{counter}" in seen:
                    counter += 1
                new_slug = f"{slug}-{counter}"
            else:
                new_slug = f"{slug}-{suffix}"
            log.warning("slug_collision_resolved", original=slug, resolved=new_slug)
            result["slug"] = new_slug
        seen.add(result["slug"])
    return results


def _dedup_sub_domains(
    named_subs: list[dict],
    parent_display_name: str,
    ancestor_display_names: set[str] | None = None,
) -> list[dict]:
    """Merge sub-domains with identical display_name, dedup slugs, avoid parent/ancestor collision."""
    merged_by_name: dict[str, dict] = {}
    for sub in named_subs:
        key = sub["display_name"]
        if key in merged_by_name:
            merged_by_name[key]["modules"].extend(sub.get("modules", []))
        else:
            merged_by_name[key] = dict(sub)
    result = list(merged_by_name.values())

    seen_slugs: set[str] = set()
    for sub in result:
        slug = sub["slug"]
        if slug in seen_slugs:
            counter = 1
            while f"{slug}-{counter}" in seen_slugs:
                counter += 1
            sub["slug"] = f"{slug}-{counter}"
        seen_slugs.add(sub["slug"])

    ancestors = (ancestor_display_names or set()) | {parent_display_name}
    for sub in result:
        if sub["display_name"] not in ancestors:
            continue
        core_name = f"{sub['display_name']}（核心）"
        if core_name in ancestors:
            desc = sub.get("description", "")
            differentiator = _extract_differentiator(desc) if desc else ""
            if differentiator:
                sub["display_name"] = f"{sub['display_name']}（{differentiator}）"
            else:
                sub["display_name"] = f"{sub['display_name']}（子域）"
        else:
            sub["display_name"] = core_name

    return result


def _collect_leaf_sub_domains(sub_tree: dict) -> list[dict]:
    """Flatten detect_sub_communities tree into leaf sub-domains with modules."""
    children = sub_tree.get("children") or []
    if not children:
        return [sub_tree]
    leaves: list[dict] = []
    for child in children:
        leaves.extend(_collect_leaf_sub_domains(child))
    return leaves


async def _louvain_fallback_clustering(
    biz_modules: list[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
) -> list[set[tuple[str, str]]]:
    """Fallback: use Louvain community detection when embeddings are unavailable."""
    from wiki.graph_community_detector import GraphCommunityDetector

    detector = GraphCommunityDetector(target_min=5, target_max=15, seed=42)

    if not edges:
        return [set(biz_modules)]

    nodes_with_edges: set[tuple[str, str]] = set()
    for src, dst, _ in edges:
        nodes_with_edges.add(src)
        nodes_with_edges.add(dst)

    connected = [n for n in biz_modules if n in nodes_with_edges]
    isolated = [n for n in biz_modules if n not in nodes_with_edges]

    communities = detector.detect(connected, edges) if connected else [set(biz_modules)]

    if isolated and communities:
        assignments = detector.assign_isolated_modules(isolated, communities)
        for idx, assigned_modules in assignments.items():
            if idx == -1:
                if assigned_modules:
                    communities.append(set(assigned_modules))
            elif 0 <= idx < len(communities):
                communities[idx].update(assigned_modules)

    return communities


def _tfidf_fallback_clustering(
    biz_modules: list[tuple[str, str]],
    module_paths: dict[str, str],
    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    module_summaries_raw: dict | None = None,
) -> list[set[tuple[str, str]]]:
    """Fallback: use TF-IDF on module names+paths when embeddings are unavailable."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.feature_extraction.text import TfidfVectorizer

    n = len(biz_modules)
    if n < 3:
        return [set(biz_modules)]

    try:
        texts = DomainSemanticClusterer.build_embedding_texts(
            biz_modules, module_summaries_raw or {}, module_paths,
        )
        if not texts or len(texts) != len(biz_modules):
            raise ValueError("build_embedding_texts returned invalid length")
    except Exception:
        texts = [
            f"{name} {_lookup_module_value(module_paths, repo, name)}"
            for repo, name in biz_modules
        ]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
    tfidf_matrix = vectorizer.fit_transform(texts)

    # Convert sparse TF-IDF to dense cosine distance
    from sklearn.metrics.pairwise import cosine_distances
    dist = cosine_distances(tfidf_matrix)

    k = min(max(2, n // 5), n - 1)
    model = AgglomerativeClustering(
        n_clusters=k, metric="precomputed", linkage="average",
    )
    labels = model.fit_predict(dist)
    clusters: dict[int, set[tuple[str, str]]] = {}
    for i, label in enumerate(labels):
        clusters.setdefault(int(label), set()).add(biz_modules[i])
    return list(clusters.values())


def _filter_biz_modules(
    entity_roles: dict[str, str],
    modules: dict[str, list[dict]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], dict[str, str], dict[str, str]]:
    """Filter modules to business-relevant roles.

    Returns: (biz_modules, supporting_excluded, module_paths, module_docstrings)
    """
    wiki_cfg = get_settings().wiki

    allowed_roles = set(DOMAIN_CLASSIFICATION_ENTITY_ROLES)
    if not wiki_cfg.classify_include_supporting:
        allowed_roles.discard(WikiEntityRole.SUPPORTING)

    biz_modules: list[tuple[str, str]] = []
    supporting_excluded: list[tuple[str, str]] = []
    module_paths: dict[str, str] = {}
    module_docstrings: dict[str, str] = {}

    for repo, mod_list in modules.items():
        for mod_dict in mod_list:
            uid = mod_dict.get("uid", "")
            props = mod_dict.get("properties", {})
            name = str(props.get("name", ""))
            path = str(props.get("path", "") or "")
            if not name:
                continue
            compound_key = _compound_key(repo, name)
            module_paths[compound_key] = path
            doc = str(props.get("business_summary", "") or props.get("docstring", "") or "")
            if doc:
                module_docstrings[compound_key] = doc

            role_str = str(entity_roles.get(uid, ""))
            try:
                role = WikiEntityRole(role_str)
            except ValueError:
                continue

            if role in allowed_roles:
                if path.startswith("<import:"):
                    continue
                if is_data_model(name, path):
                    continue
                biz_modules.append((repo, name))
            elif role == WikiEntityRole.SUPPORTING and not wiki_cfg.classify_include_supporting:
                supporting_excluded.append((repo, name))

    return biz_modules, supporting_excluded, module_paths, module_docstrings


def _route_supporting_modules(
    supporting_excluded: list[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    domain_mapping: dict[str, list[tuple[str, str]]],
) -> None:
    """Assign excluded SUPPORTING modules to domains via call edges or largest domain."""
    if not supporting_excluded or not domain_mapping:
        return

    module_to_domain: dict[tuple[str, str], str] = {}
    for slug, mod_list in domain_mapping.items():
        for mod in mod_list:
            module_to_domain[mod] = slug

    largest_domain = max(domain_mapping, key=lambda s: len(domain_mapping[s]))

    for mod in supporting_excluded:
        best_domain: str | None = None
        best_weight = 0
        for src, dst, weight in edges:
            if src == mod and dst in module_to_domain:
                if weight > best_weight:
                    best_weight = weight
                    best_domain = module_to_domain[dst]
            elif dst == mod and src in module_to_domain:
                if weight > best_weight:
                    best_weight = weight
                    best_domain = module_to_domain[src]

        target = best_domain or largest_domain
        domain_mapping.setdefault(target, []).append(mod)
        module_to_domain[mod] = target


def _prune_deleted_modules_from_mapping(
    domain_mapping: dict[str, list[tuple[str, str]]],
    current_modules: set[tuple[str, str]],
) -> None:
    """Remove modules no longer present in the graph from each domain bucket."""
    for slug in list(domain_mapping.keys()):
        domain_mapping[slug] = [
            (repo, name) for repo, name in domain_mapping[slug] if (repo, name) in current_modules
        ]
        if not domain_mapping[slug]:
            del domain_mapping[slug]


def _assign_changed_modules_incremental(
    changed_biz: list[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    domain_mapping: dict[str, list[tuple[str, str]]],
    existing_mod_to_domain: dict[tuple[str, str] | str, str],
) -> None:
    """Assign changed/new modules to existing domains via prior mapping or call edges."""
    if not domain_mapping:
        return

    for repo, name in changed_biz:
        compound = (repo, name)
        slug = existing_mod_to_domain.get(compound) or existing_mod_to_domain.get(name)
        if slug and slug in domain_mapping:
            if compound not in domain_mapping[slug]:
                domain_mapping[slug].append(compound)
            continue

        assigned = False
        for edge_src, edge_dst, _ in edges:
            neighbor: tuple[str, str] | None = None
            if edge_src[0] == repo and edge_src[1] == name:
                neighbor = edge_dst
            elif edge_dst[0] == repo and edge_dst[1] == name:
                neighbor = edge_src
            if neighbor:
                neighbor_slug = existing_mod_to_domain.get(neighbor) or existing_mod_to_domain.get(neighbor[1])
                if neighbor_slug and neighbor_slug in domain_mapping:
                    domain_mapping[neighbor_slug].append((repo, name))
                    assigned = True
                    break
        if not assigned:
            largest = max(domain_mapping, key=lambda s: len(domain_mapping[s]))
            domain_mapping[largest].append((repo, name))


def _assign_pinned_modules(
    pinned_modules: dict[str, str],
    modules: dict[str, list[dict]],
    domain_mapping: dict[str, list[tuple[str, str]]],
) -> None:
    """Force pinned modules into their target domains after clustering/assignment."""
    if not pinned_modules or not domain_mapping:
        return

    for key, target_slug in pinned_modules.items():
        pin_repo, mod_name = _split_pinned_module_key(key)
        for repo, mod_list in modules.items():
            if pin_repo is not None and repo != pin_repo:
                continue
            for mod_dict in mod_list:
                props = mod_dict.get("properties", {})
                if str(props.get("name", "")) != mod_name:
                    continue
                pair = (repo, mod_name)
                for slug, pairs in list(domain_mapping.items()):
                    if pair in pairs and slug != target_slug:
                        domain_mapping[slug] = [p for p in pairs if p != pair]
                domain_mapping.setdefault(target_slug, [])
                if pair not in domain_mapping[target_slug]:
                    domain_mapping[target_slug].append(pair)
                break


async def _embedding_clustering(
    biz_modules: list[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    module_paths: dict[str, str],
    module_summaries_raw: dict[str, dict[str, Any]],
    embedding_cache: dict[str, list[float]] | None = None,
) -> tuple[list[set[tuple[str, str]]], np.ndarray | None]:
    """Primary: semantic embedding clustering. Returns (clusters, embeddings_array)."""
    from core.config import get_settings
    from indexer.embedding_generator import EmbeddingGenerator

    texts = DomainSemanticClusterer.build_embedding_texts(
        biz_modules, module_summaries_raw, module_paths,
    )

    cache = embedding_cache if embedding_cache is not None else {}
    try:
        config = get_settings().embedding
        generator = EmbeddingGenerator.shared(config)
        embedding_lists = await _embed_texts_with_cache(texts, cache, generator)
        embeddings = np.array(embedding_lists, dtype=np.float32)
    except Exception:
        log.warning("embedding_generation_failed_fallback_tfidf", exc_info=True)
        try:
            return _tfidf_fallback_clustering(
                biz_modules, module_paths, edges, module_summaries_raw,
            ), None
        except Exception:
            log.warning("tfidf_fallback_failed_fallback_louvain", exc_info=True)
            return await _louvain_fallback_clustering(biz_modules, edges), None

    clusterer = DomainSemanticClusterer()
    communities = clusterer.cluster(embeddings, biz_modules, edges)
    return communities, embeddings


def _structural_quality_check(
    domain_mapping: dict[str, list],
    module_count_total: int,
) -> list[str]:
    """Check structural quality of domain decomposition.

    Returns list of warning strings. Empty list means good quality.
    """
    warnings: list[str] = []
    single = [s for s, m in domain_mapping.items() if len(m) == 1]
    if len(single) > len(domain_mapping) * 0.3:
        warnings.append(f"FRAGMENTATION: {len(single)} single-module domains out of {len(domain_mapping)}")
    for slug, modules in domain_mapping.items():
        if len(modules) > module_count_total * 0.4:
            warnings.append(f"MEGA_DOMAIN: {slug} has {len(modules)}/{module_count_total} modules")
    if len(domain_mapping) < 3 and module_count_total > 20:
        warnings.append(f"TOO_FEW: only {len(domain_mapping)} domains for {module_count_total} modules")
    if len(domain_mapping) > module_count_total * 0.5:
        warnings.append(f"TOO_MANY: {len(domain_mapping)} domains for {module_count_total} modules")
    return warnings


def _domain_decomposition_quality_check(
    new_mapping: dict[str, list],
    baseline_mapping: dict[str, list],
) -> tuple[bool, list[str]]:
    """Compare new decomposition against baseline.

    Returns (passed, warnings). Critical warnings cause failure.
    """
    warnings: list[str] = []
    disappeared = set(baseline_mapping.keys()) - set(new_mapping.keys())
    for slug in disappeared:
        mod_count = len(baseline_mapping[slug])
        severity = "CRITICAL" if mod_count >= 5 else "WARNING"
        warnings.append(f"DOMAIN_DISAPPEARED({severity}): {slug} ({mod_count} modules)")
    if len(new_mapping) < len(baseline_mapping) * 0.5:
        warnings.append(f"DOMAIN_COLLAPSE: {len(baseline_mapping)}→{len(new_mapping)}")
    if len(new_mapping) > len(baseline_mapping) * 2:
        warnings.append(f"DOMAIN_EXPLOSION: {len(baseline_mapping)}→{len(new_mapping)}")
    critical = [w for w in warnings if "CRITICAL" in w or "COLLAPSE" in w]
    return len(critical) == 0, warnings


async def _agent_review_decomposition(
    llm: Any,
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
    module_summaries: dict[str, str],
) -> tuple[str, list[str]]:
    """LLM-based semantic review of domain decomposition.

    Returns (overall_quality, warning_strings).
    Gracefully falls back to ("acceptable", []) on any failure.
    """
    try:
        listing_lines: list[str] = []
        for slug, modules in sorted(domain_mapping.items(), key=lambda x: -len(x[1])):
            display = domain_display_names.get(slug, slug)
            listing_lines.append(f"- {slug} ({display}) — {len(modules)} modules:")
            for repo, mod_name in modules[:8]:
                summary = module_summaries.get(mod_name, "")
                listing_lines.append(f"  - {mod_name}: {summary[:80]}" if summary else f"  - {mod_name}")

        prompt = (
            "You are a software architecture reviewer. Evaluate the following domain decomposition.\n\n"
            "Domains:\n" + "\n".join(listing_lines) + "\n\n"
            "Evaluate quality and return JSON:\n"
            '{"overall_quality": "good"|"acceptable"|"needs_revision", '
            '"issues": [{"domain_slug": "...", "issue_type": "misplaced_module"|"semantic_overlap"|"naming_unclear"|"too_broad"|"too_narrow", '
            '"description": "...", "severity": "critical"|"warning"|"info"}]}'
        )

        result = await llm.complete_json(
            [{"role": "user", "content": prompt}],
            {
                "type": "object",
                "properties": {
                    "overall_quality": {"type": "string", "enum": ["good", "acceptable", "needs_revision"]},
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "domain_slug": {"type": "string"},
                                "issue_type": {"type": "string"},
                                "description": {"type": "string"},
                                "severity": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["overall_quality", "issues"],
                "title": "DomainReviewOutput",
            },
        )

        quality = result.get("overall_quality", "acceptable")
        issues = result.get("issues", [])
        warning_strs = []
        for issue in issues:
            if isinstance(issue, dict):
                warning_strs.append(
                    f"AGENT_REVIEW({issue.get('severity', 'info')}): "
                    f"{issue.get('domain_slug', '?')} — {issue.get('issue_type', '?')}: "
                    f"{issue.get('description', '')}"
                )
        return quality, warning_strs
    except Exception:
        log.warning("agent_review_decomposition_failed", exc_info=True)
        return "acceptable", []


def _assign_new_modules_to_nearest(
    new_modules: set[tuple[str, str]],
    domain_mapping: dict[str, list[tuple[str, str]]],
    embeddings: dict[str, list[float] | Any],
) -> None:
    """Assign new modules to the semantically nearest existing domain.

    Modifies domain_mapping in place.
    """
    if not new_modules or not domain_mapping:
        return

    domain_centroids: dict[str, Any] = {}
    for slug, pairs in domain_mapping.items():
        vecs = []
        for _, mod_name in pairs:
            emb = embeddings.get(mod_name)
            if emb is not None:
                vecs.append(np.array(emb, dtype=np.float32))
        if vecs:
            domain_centroids[slug] = np.mean(vecs, axis=0)

    if not domain_centroids:
        return

    for repo, mod_name in new_modules:
        emb = embeddings.get(mod_name)
        if emb is None:
            continue
        mod_vec = np.array(emb, dtype=np.float32)
        best_slug = ""
        best_sim = -1.0
        for slug, centroid in domain_centroids.items():
            norm_a = np.linalg.norm(mod_vec)
            norm_b = np.linalg.norm(centroid)
            if norm_a > 0 and norm_b > 0:
                sim = float(np.dot(mod_vec, centroid) / (norm_a * norm_b))
            else:
                sim = 0.0
            if sim > best_sim:
                best_sim = sim
                best_slug = slug
        if best_slug:
            domain_mapping[best_slug].append((repo, mod_name))
            log.info("new_module_assigned", module=mod_name, domain=best_slug, similarity=round(best_sim, 3))


async def graph_driven_domain_decompose_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Semantic embedding domain decomposition with LLM refinement.

    Primary path: embed module summaries → HAC clustering → LLM naming → global review.
    Falls back to Louvain when embeddings are unavailable, or old LLM classification
    when graph_store is missing.
    """
    configurable = (config or {}).get("configurable", {})
    graph_store = configurable.get("graph_store")
    llm = configurable.get("llm")

    existing_domain_mapping: dict[str, list[tuple[str, str]]] = state.get("existing_domain_mapping", {})
    is_incremental = state.get("is_incremental", False) and bool(existing_domain_mapping)
    affected_modules: set[str] = set(state.get("affected_modules", []))
    pinned_modules: dict[str, str] = state.get("pinned_modules", {})

    if graph_store is None:
        log.warning("graph_domain_decompose_skip", reason="no graph_store")
        return {
            "domain_mapping": {},
            "domain_display_names": {},
            "domain_tree": [],
            "affected_domains": [],
            "module_call_edges": [],
        }

    # --- Step 0: Filter to BIZ modules ---
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})
    repositories = state.get("repositories", [])

    biz_modules, supporting_excluded, module_paths, module_docstrings = _filter_biz_modules(
        entity_roles, modules,
    )

    if pinned_modules:
        biz_modules = [
            (repo, name) for repo, name in biz_modules
            if not is_module_pinned(pinned_modules, repo, name)
        ]

    if not biz_modules and not pinned_modules:
        return {
            "domain_mapping": {},
            "domain_display_names": {},
            "domain_tree": [],
            "affected_domains": [],
            "module_call_edges": [],
        }

    valid_modules_set = set(biz_modules)

    # --- Step 1.5: Collect module summaries from pipeline state ---
    module_summaries_raw: dict[str, dict[str, Any]] = state.get("module_summaries", {}) or {}

    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]] = []
    query_errors: list[str] = []
    skip_full_clustering = False
    use_existing_tree = False
    embedding_cache: dict[str, list[float]] = dict(state.get("embedding_cache") or {})
    domain_mapping: dict[str, list[tuple[str, str]]] = {}
    domain_display_names: dict[str, str] = dict(state.get("domain_display_names") or {})
    communities_named: list[dict[str, Any]] = []
    sub_trees: dict[str, list[dict]] = {}
    embeddings: np.ndarray | None = None
    namer: GraphDomainNamer | None = None
    used_names: list[str] = []

    if is_incremental:
        changed_biz: list[tuple[str, str]] = []
        unchanged_biz: list[tuple[str, str]] = []
        for repo, name in biz_modules:
            compound = _compound_key(repo, name)
            if compound in affected_modules or name in affected_modules:
                changed_biz.append((repo, name))
            else:
                unchanged_biz.append((repo, name))

        if not changed_biz:
            log.info("graph_incremental_no_changes", unchanged=len(unchanged_biz))
            domain_mapping = {slug: list(pairs) for slug, pairs in existing_domain_mapping.items()}
            current_modules = set(biz_modules)
            _prune_deleted_modules_from_mapping(domain_mapping, current_modules)
            for slug in domain_mapping:
                domain_display_names.setdefault(slug, slug)
            skip_full_clustering = True
            use_existing_tree = bool(state.get("domain_tree"))
        else:
            log.info(
                "graph_incremental_clustering",
                changed=len(changed_biz),
                unchanged=len(unchanged_biz),
            )
            edges, query_errors = await fetch_module_call_edges(
                graph_store, repositories, valid_modules_set,
            )
            if query_errors:
                log.warning("graph_domain_decompose_query_errors", errors=query_errors)
            log.info(
                "graph_domain_decompose_edges",
                total_modules=len(biz_modules),
                total_edges=len(edges),
            )
            existing_mod_to_domain: dict[tuple[str, str] | str, str] = {}
            for slug, pairs in existing_domain_mapping.items():
                for _repo, mod_name in pairs:
                    existing_mod_to_domain[(_repo, mod_name)] = slug
                    existing_mod_to_domain.setdefault(mod_name, slug)

            domain_mapping = {slug: list(pairs) for slug, pairs in existing_domain_mapping.items()}
            current_modules = set(biz_modules)
            _prune_deleted_modules_from_mapping(domain_mapping, current_modules)
            _assign_changed_modules_incremental(
                changed_biz, edges, domain_mapping, existing_mod_to_domain,
            )
            for slug in domain_mapping:
                domain_display_names.setdefault(slug, slug)

            domains_changed = False
            for slug, pairs in domain_mapping.items():
                old_pairs = set(existing_domain_mapping.get(slug, []))
                new_pairs = set(map(tuple, pairs))
                if old_pairs != new_pairs:
                    domains_changed = True
                    break

            skip_full_clustering = True
            use_existing_tree = bool(state.get("domain_tree")) and not domains_changed

    if not skip_full_clustering:
        if not edges:
            edges, query_errors = await fetch_module_call_edges(
                graph_store, repositories, valid_modules_set,
            )
            if query_errors:
                log.warning("graph_domain_decompose_query_errors", errors=query_errors)
            log.info(
                "graph_domain_decompose_edges",
                total_modules=len(biz_modules),
                total_edges=len(edges),
            )

        # --- Step 2: Semantic embedding clustering (fallback: Louvain) ---
        communities, embeddings = await _embedding_clustering(
            biz_modules, edges, module_paths, module_summaries_raw,
            embedding_cache=embedding_cache,
        )

        # --- Step 3: LLM Naming with module_infos (parallelized) ---
        namer = GraphDomainNamer(llm)
        shared_used_names: list[str] = []

        async def _name_community(community: set[tuple[str, str]]) -> dict[str, Any]:
            module_infos = []
            for repo_id, mod_name in sorted(community):
                summary_data = _lookup_module_value(module_summaries_raw, repo_id, mod_name)
                summary_text = ""
                if isinstance(summary_data, dict):
                    summary_text = str(summary_data.get("summary_text", ""))
                elif isinstance(summary_data, str):
                    summary_text = summary_data
                doc = _lookup_module_value(module_docstrings, repo_id, mod_name) or ""
                if doc and doc not in summary_text:
                    summary_text = f"[{doc}] {summary_text}" if summary_text else doc
                module_infos.append({
                    "name": mod_name,
                    "path": _lookup_module_value(module_paths, repo_id, mod_name) or "",
                    "summary": summary_text,
                })
            await acquire_llm_quota(config, estimated_tokens=1500)
            naming = await namer.name_community(
                module_infos=module_infos,
                used_names=list(shared_used_names),
                business_id=state.get("business_id", ""),
            )
            return {
                "slug": naming["slug"],
                "display_name": naming["display_name"],
                "description": naming.get("description", ""),
                "modules": sorted(community),
            }

        naming_tasks = [_name_community(community) for community in communities]
        results = await asyncio.gather(*naming_tasks, return_exceptions=True)
        valid_results: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("domain_naming_task_failed", exc_info=r)
            elif isinstance(r, dict):
                valid_results.append(r)

        communities_named = _dedup_parallel_naming_results(valid_results, list(shared_used_names))
        used_names = list(shared_used_names) + [c["slug"] for c in communities_named]

        # --- Step 4: Build domain_mapping ---
        domain_mapping = {}
        domain_display_names = {}
        for c in communities_named:
            domain_mapping[c["slug"]] = list(c["modules"])
            domain_display_names[c["slug"]] = c["display_name"]

    _assign_pinned_modules(pinned_modules, modules, domain_mapping)
    _route_supporting_modules(supporting_excluded, edges, domain_mapping)

    if not skip_full_clustering:
        # --- Step 5: Post-processing (safety nets) ---
        domain_mapping, domain_display_names = _ensure_ascii_keys(domain_mapping, domain_display_names)
        domain_mapping, domain_display_names = _consolidate_split_entities(domain_mapping, domain_display_names)
        wiki_cfg = get_settings().wiki
        skip_llm_merge = llm and wiki_cfg.skip_llm_merge_when_corrector_enabled
        if llm and not skip_llm_merge:
            await acquire_llm_quota(config, estimated_tokens=2000)
            domain_mapping, domain_display_names = await _merge_domains_by_llm(
                domain_mapping, domain_display_names, llm,
            )
        elif not llm:
            domain_mapping, domain_display_names = await _merge_domains_by_embedding(
                domain_mapping, domain_display_names,
                embedding_cache=embedding_cache,
            )

        # --- Step 5.5: LLM Global Consistency Review ---
        module_summaries_flat = _build_module_summaries_flat_for_corrector(
            biz_modules, module_summaries_raw,
        )

        corrector = GraphSemanticCorrector(llm)
        paths_for_corrector = _build_paths_for_corrector(biz_modules, module_paths)
        domain_mapping, domain_display_names = await corrector.review_global_consistency(
            domain_mapping, domain_display_names, paths_for_corrector, module_summaries_flat,
            business_id=state.get("business_id", ""),
            module_details=module_summaries_raw,
            language=_resolve_content_language(state),
            anchored_slugs=frozenset(state.get("anchored_slugs") or set()),
        )

        # Rebuild communities_named after review
        communities_named = []
        for slug, module_list in domain_mapping.items():
            communities_named.append({
                "slug": slug,
                "display_name": domain_display_names.get(slug, slug),
                "modules": module_list,
            })

        # --- Step 5.6: F9 Domain Protection — Recovery + Quality Gate ---
        anchored_slugs = state.get("anchored_slugs") or set()
        anchor_display_names_state = state.get("anchor_display_names") or {}
        domain_baseline = state.get("domain_baseline") or {}

        # P3: Recover anchored domains that disappeared
        persistence = configurable.get("persistence")
        if anchored_slugs and persistence:
            for slug in anchored_slugs:
                if slug not in domain_mapping:
                    try:
                        anchor_modules = await persistence.list_domain_modules(
                            state.get("business_id", ""), slug,
                        )
                        if anchor_modules:
                            mod_tuples = [
                                (str(m.get("repository", "")), str(m["module_name"])) for m in anchor_modules
                            ]
                            for other_slug in list(domain_mapping.keys()):
                                domain_mapping[other_slug] = [
                                    m for m in domain_mapping[other_slug] if m not in mod_tuples
                                ]
                            domain_mapping[slug] = mod_tuples
                            domain_display_names[slug] = anchor_display_names_state.get(slug, slug)
                            log.warning("anchored_domain_recovered", slug=slug, modules=len(mod_tuples))
                    except Exception:
                        log.warning("anchored_domain_recovery_failed", slug=slug, exc_info=True)

        # S3a: Structural quality check
        struct_warnings = _structural_quality_check(
            domain_mapping, sum(len(v) for v in domain_mapping.values()),
        )
        for w in struct_warnings:
            log.warning("decompose_structural_warning", warning=w)

        # S3b: Agent semantic review (only when LLM available)
        quality_level = "acceptable"
        semantic_warnings: list[str] = []
        if llm:
            module_summaries_flat_for_review = _build_module_summaries_flat_for_corrector(
                biz_modules, module_summaries_raw,
            )
            quality_level, semantic_warnings = await _agent_review_decomposition(
                llm, domain_mapping, domain_display_names, module_summaries_flat_for_review,
            )
            for w in semantic_warnings:
                log.warning("decompose_semantic_warning", warning=w)

        # S3: Combined quality gate
        all_quality_warnings = struct_warnings + semantic_warnings
        has_critical = any("CRITICAL" in w for w in all_quality_warnings)
        needs_revision = quality_level == "needs_revision"

        if domain_baseline:
            baseline_passed, baseline_warnings = _domain_decomposition_quality_check(
                domain_mapping, domain_baseline,
            )
            all_quality_warnings.extend(baseline_warnings)
            for w in baseline_warnings:
                log.warning("decompose_baseline_warning", warning=w)

            if has_critical or needs_revision or not baseline_passed:
                log.error(
                    "decompose_quality_gate_failed",
                    quality=quality_level,
                    warnings=all_quality_warnings,
                )
                # Fall back to baseline + assign new modules incrementally
                domain_mapping = {slug: list(pairs) for slug, pairs in domain_baseline.items()}
                domain_display_names = {
                    slug: anchor_display_names_state.get(slug, slug)
                    for slug in domain_mapping
                }
                # Find new modules not in baseline
                baseline_mods = {m for pairs in domain_baseline.values() for m in pairs}
                new_mods = set(biz_modules) - baseline_mods
                if new_mods and embedding_cache:
                    _assign_new_modules_to_nearest(new_mods, domain_mapping, embedding_cache)
        elif all_quality_warnings:
            log.warning("decompose_quality_warnings", quality=quality_level, count=len(all_quality_warnings))

        # Store warnings in state for downstream visibility
        state["decomposition_warnings"] = all_quality_warnings

        # Rebuild communities_named after quality gate (mapping may have changed)
        communities_named = []
        for slug, module_list in domain_mapping.items():
            communities_named.append({
                "slug": slug,
                "display_name": domain_display_names.get(slug, slug),
                "modules": module_list,
            })

        # --- Step 6: Domain stabilizer ---
        try:
            from wiki.domain_stabilizer import DomainStabilizer

            stabilizer = DomainStabilizer(graph_store)
            rename_map = await stabilizer.stabilize(list(domain_mapping.keys()))
            if any(k != v for k, v in rename_map.items()):
                stabilized: dict[str, list] = {}
                updated_display: dict[str, str] = {}
                for proposed, pairs in domain_mapping.items():
                    stable = rename_map.get(proposed, proposed)
                    stabilized.setdefault(stable, []).extend(pairs)
                    if proposed in domain_display_names:
                        updated_display[stable] = domain_display_names[proposed]
                domain_mapping = stabilized
                domain_display_names.update(updated_display)
        except Exception:
            log.warning("graph_domain_stabilizer_failed", exc_info=True)

        # --- Step 6.5: Collision slug cleanup ---
        domain_mapping, domain_display_names = _cleanup_collision_slugs(
            domain_mapping, domain_display_names,
        )

        # --- Step 6.55: Infrastructure domain filtering ---
        wiki_cfg = get_settings().wiki
        domain_mapping, domain_display_names = _filter_infrastructure_domains(
            domain_mapping, domain_display_names, wiki_cfg.infrastructure_slug_keywords, edges=edges,
        )

        # --- Step 6.6: Domain budget enforcement ---
        budget = wiki_cfg.domain_budget_max
        domain_mapping, domain_display_names = _enforce_domain_budget(
            domain_mapping, domain_display_names, budget=budget,
        )

        # Rebuild communities_named after stabilizer (slugs may have changed)
        communities_named = []
        for slug, module_list in domain_mapping.items():
            communities_named.append({
                "slug": slug,
                "display_name": domain_display_names.get(slug, slug),
                "modules": module_list,
            })

        # --- Step 7: Recursive sub-domain splitting ---
        business_id = state.get("business_id", "")

        async def _recursive_split(
            community_modules: list[tuple[str, str]],
            parent_used_names: list[str],
            parent_display: str,
            depth: int,
            ancestor_display_names: set[str] | None = None,
        ) -> list[dict]:
            ancestors = (ancestor_display_names or set()) | {parent_display}
            split_threshold, max_split_depth = _get_split_params()
            if len(community_modules) <= split_threshold or depth >= max_split_depth:
                return []

            clusterer = DomainSemanticClusterer()
            if embeddings is not None:
                mod_set = set(community_modules)
                indices = [i for i, m in enumerate(biz_modules) if m in mod_set]
                if not indices:
                    return []
                sub_embeddings = embeddings[indices]
                sub_modules = [biz_modules[i] for i in indices]
                sub_clusters = clusterer.cluster_sub_domains(sub_embeddings, sub_modules, edges)
            else:
                from wiki.graph_community_detector import GraphCommunityDetector
                detector = GraphCommunityDetector(target_min=2, target_max=5, seed=42)
                community_set = set(community_modules)
                sub_result = detector.detect_sub_communities(
                    community_set, edges, max_depth=2, max_leaf_size=split_threshold,
                )
                sub_clusters_raw: list[set[tuple[str, str]]] = []
                for root in sub_result:
                    for leaf in _collect_leaf_sub_domains(root):
                        mods = leaf.get("modules", [])
                        if mods:
                            sub_clusters_raw.append(set(mods))
                sub_clusters = sub_clusters_raw if len(sub_clusters_raw) > 1 else [community_set]

            if len(sub_clusters) <= 1:
                return []

            sem = PipelineConcurrency.semaphore("domain_naming")

            async def _name_one_sub(sub_cluster: set[tuple[str, str]]) -> dict[str, Any]:
                sub_infos = []
                for repo_id, mod_name in sorted(sub_cluster):
                    summary_data = _lookup_module_value(module_summaries_raw, repo_id, mod_name)
                    summary_text = ""
                    if isinstance(summary_data, dict):
                        summary_text = str(summary_data.get("summary_text", ""))
                    elif isinstance(summary_data, str):
                        summary_text = summary_data
                    doc = _lookup_module_value(module_docstrings, repo_id, mod_name) or ""
                    if doc and doc not in summary_text:
                        summary_text = f"[{doc}] {summary_text}" if summary_text else doc
                    sub_infos.append({
                        "name": mod_name,
                        "path": _lookup_module_value(module_paths, repo_id, mod_name) or "",
                        "summary": summary_text,
                    })
                async with sem:
                    assert namer is not None
                    return await namer.name_community(
                        module_infos=sub_infos,
                        used_names=list(parent_used_names),
                        business_id=business_id,
                    )

            naming_results = await asyncio.gather(
                *[_name_one_sub(sc) for sc in sub_clusters],
                return_exceptions=True,
            )

            valid_results: list[dict[str, Any]] = []
            valid_clusters: list[set[tuple[str, str]]] = []
            for result, sub_cluster in zip(naming_results, sub_clusters, strict=True):
                if isinstance(result, Exception):
                    log.warning("sub_domain_naming_failed", exc_info=result)
                else:
                    result["modules"] = [
                        f"{repo_id}.{mod_name}" for repo_id, mod_name in sorted(sub_cluster)
                    ]
                    valid_results.append(result)
                    valid_clusters.append(sub_cluster)

            if not valid_results:
                return []

            deduped_results = _dedup_parallel_naming_results(valid_results, list(parent_used_names))
            all_slugs = list(parent_used_names) + [r["slug"] for r in deduped_results]

            async def _build_named_sub(
                sub_naming: dict[str, Any],
                sub_cluster: set[tuple[str, str]],
            ) -> dict[str, Any]:
                child_ancestors = set(ancestors) | {sub_naming["display_name"]}
                if sub_naming["display_name"] in ancestors:
                    child_ancestors.add(f"{sub_naming['display_name']}（核心）")
                children = await _recursive_split(
                    list(sub_cluster),
                    list(all_slugs),
                    sub_naming["display_name"],
                    depth + 1,
                    ancestor_display_names=child_ancestors,
                )
                return {
                    "slug": sub_naming["slug"],
                    "display_name": sub_naming["display_name"],
                    "modules": list(sub_cluster),
                    "children": children,
                }

            named_subs: list[dict] = []
            if len(deduped_results) > 1:
                sub_tasks = [
                    _build_named_sub(sub_naming, sub_cluster)
                    for sub_naming, sub_cluster in zip(deduped_results, valid_clusters, strict=True)
                ]
                sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)
                for sub_result in sub_results:
                    if isinstance(sub_result, dict):
                        named_subs.append(sub_result)
                    elif isinstance(sub_result, BaseException):
                        log.warning("sub_domain_recursive_split_failed", exc_info=sub_result)
            else:
                for sub_naming, sub_cluster in zip(deduped_results, valid_clusters, strict=True):
                    named_subs.append(await _build_named_sub(sub_naming, sub_cluster))

            named_subs = _dedup_sub_domains(
                named_subs,
                parent_display,
                ancestor_display_names=ancestors,
            )
            return _filter_infra_sub_domains(named_subs, wiki_cfg.infrastructure_slug_keywords)

        for c in communities_named:
            slug = c["slug"]
            community_modules = list(c["modules"])
            parent_display = domain_display_names.get(slug, slug)
            subs = await _recursive_split(
                community_modules,
                used_names,
                parent_display,
                0,
                ancestor_display_names={parent_display},
            )
            if subs and len(subs) > 1:
                sub_trees[slug] = subs
    else:
        communities_named = [
            {
                "slug": slug,
                "display_name": domain_display_names.get(slug, slug),
                "modules": list(pairs),
            }
            for slug, pairs in domain_mapping.items()
        ]

    # --- Step 8: Build domain_tree ---
    if use_existing_tree and state.get("domain_tree"):
        domain_tree = state.get("domain_tree")
    else:
        domain_tree = _collapse_empty_shells(_build_domain_tree(communities_named, sub_trees))

    if domain_tree:
        _review_subdomain_placement(domain_tree, embeddings)

    # --- Step 9: Determine affected_domains ---
    if is_incremental:
        affected_domains = list({
            slug for slug, pairs in domain_mapping.items()
            if any(
                _compound_key(repo, name) in affected_modules or name in affected_modules
                for repo, name in pairs
            )
        })
    else:
        affected_domains = list(domain_mapping.keys())

    log.info(
        "graph_domain_decompose_done",
        domains=len(domain_mapping),
        total_modules=sum(len(v) for v in domain_mapping.values()),
        with_sub_domains=len(sub_trees),
    )

    module_call_edges = [
        {
            "source_repo": src[0],
            "source": src[1],
            "target_repo": dst[0],
            "target": dst[1],
            "source_key": _compound_key(src[0], src[1]),
            "target_key": _compound_key(dst[0], dst[1]),
            "weight": w,
        }
        for src, dst, w in edges
    ]

    # --- Build term glossary from domain names + module descriptions ---
    from core.config import get_settings as _get_settings

    wiki_cfg = _get_settings().wiki
    term_glossary: dict[str, str] = {}
    for slug, display_name in domain_display_names.items():
        readable_slug = slug.replace("-", " ").replace("_", " ")
        if readable_slug != display_name and display_name:
            term_glossary[readable_slug] = display_name
            if "-" in slug:
                term_glossary[slug] = display_name

    if module_summaries_raw:
        for _mod_key, summary in module_summaries_raw.items():
            if isinstance(summary, dict):
                cn_name = summary.get("chinese_name") or summary.get("cn_name", "")
                en_name = summary.get("english_name") or summary.get("en_name", "")
                if cn_name and en_name and cn_name != en_name:
                    term_glossary.setdefault(en_name.lower(), cn_name)

    if wiki_cfg.term_overrides:
        term_glossary.update(wiki_cfg.term_overrides)

    return {
        "domain_mapping": domain_mapping,
        "domain_display_names": domain_display_names,
        "domain_tree": domain_tree,
        "affected_domains": affected_domains,
        "module_call_edges": module_call_edges,
        "embedding_cache": embedding_cache,
        "term_glossary": term_glossary,
    }
