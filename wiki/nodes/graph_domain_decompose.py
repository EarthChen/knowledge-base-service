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
from wiki.agents.domain_review_agent import DomainReviewAgent
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


def _extract_package_from_path(path: str) -> list[str]:
    """Extract package/directory segments from a module file path."""
    if not path:
        return []
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        return []
    parts = normalized.split("/")
    if len(parts) <= 1:
        return parts
    return parts[:-1]


_MAX_PACKAGE_PREFIXES = 50


def _build_package_tree(module_paths: dict[str, str]) -> str:
    """Build a human-readable package tree for LLM context."""
    from collections import defaultdict

    tree: dict[str, list[str]] = defaultdict(list)
    seen_modules: set[str] = set()
    for compound_key, path in module_paths.items():
        pkg_parts = _extract_package_from_path(path)
        prefix = ".".join(pkg_parts[:4]) if len(pkg_parts) >= 4 else ".".join(pkg_parts)
        if not prefix:
            continue
        module_name = compound_key.split("|", 1)[-1] if "|" in compound_key else compound_key
        key = (prefix, module_name)
        if key not in seen_modules:
            seen_modules.add(key)
            tree[prefix].append(module_name)

    lines: list[str] = []
    sorted_pkgs = sorted(tree.items())
    for pkg, modules in sorted_pkgs[:_MAX_PACKAGE_PREFIXES]:
        lines.append(f"  {pkg}/ ({len(modules)} modules)")
        for mod in modules[:5]:
            lines.append(f"    - {mod}")
        if len(modules) > 5:
            lines.append(f"    ... +{len(modules) - 5} more")
    if len(sorted_pkgs) > _MAX_PACKAGE_PREFIXES:
        lines.append(f"  ... +{len(sorted_pkgs) - _MAX_PACKAGE_PREFIXES} more packages")
    return "\n".join(lines)


def _build_cross_domain_edges_summary(
    edges: list[tuple[tuple[str, str], tuple[str, str], int]],
    domain_mapping: dict[str, list[tuple[str, str]]],
    top_n: int = 15,
) -> str:
    """Summarize top cross-domain call relationships."""
    mod_to_domain: dict[tuple[str, str], str] = {}
    for slug, pairs in domain_mapping.items():
        for repo, mod_name in pairs:
            mod_to_domain[(repo, mod_name)] = slug

    cross_edges: list[tuple[str, str, str, str, int]] = []
    edge_weights: dict[tuple[str, str, str, str], int] = {}
    for (r1, m1), (r2, m2), weight in edges:
        d1 = mod_to_domain.get((r1, m1))
        d2 = mod_to_domain.get((r2, m2))
        if d1 and d2 and d1 != d2:
            key = (m1, m2, d1, d2)
            edge_weights[key] = edge_weights.get(key, 0) + weight
    cross_edges = [(m1, m2, d1, d2, w) for (m1, m2, d1, d2), w in edge_weights.items()]
    cross_edges.sort(key=lambda x: -x[4])

    lines = [
        f"  {caller}({dom_a}) → {callee}({dom_b}) [{w}次]"
        for caller, callee, dom_a, dom_b, w in cross_edges[:top_n]
    ]
    return "\n".join(lines) if lines else "  (无显著跨域调用)"


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
_FAN_IN_MIN_MODULE_COUNT = 6

_INFRA_CLASS_SUFFIXES = (
    "Impl",
    "Configuration",
    "Config",
    "TypeHandler",
    "Aspect",
    "Interceptor",
    "Filter",
    "Wrapper",
    "Executor",
    "RemoteService",
)
_BUSINESS_HANDLER_PREFIXES = (
    "Family",
    "Intimacy",
    "Relation",
    "ClosedFriend",
    "Guild",
    "User",
    "Member",
    "Rank",
)
_ABSTRACT_MODULE_SUFFIXES = ("Base", "Abstract", "Interface", "Mixin")


def _is_infra_handler(name: str) -> bool:
    """Return True only for infrastructure-level handlers (not business event handlers)."""
    if not name.endswith("Handler"):
        return False
    for prefix in _BUSINESS_HANDLER_PREFIXES:
        if name.startswith(prefix):
            return False
    return True


def _is_infra_module_path(path: str, patterns: list[str]) -> bool:
    """True when module file path matches a configured infrastructure pattern."""
    if not path or not patterns:
        return False
    normalized = path.replace("\\", "/").lower()
    for pattern in patterns:
        p = pattern.lower().strip()
        if not p:
            continue
        if p in normalized:
            return True
    return False


def _is_abstract_module_name(name: str) -> bool:
    """True for PascalCase base/interface style module names."""
    if not _PASCAL_CASE_RE.match(name):
        return False
    return any(name.endswith(suffix) for suffix in _ABSTRACT_MODULE_SUFFIXES)


def _compute_module_fan_in_ratios(
    biz_modules: set[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], int]],
) -> dict[tuple[str, str], float]:
    """Return per-module ratio of distinct callers to (total_modules - 1)."""
    if len(biz_modules) <= 1:
        return {}
    callers: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for src, tgt, _weight in edges:
        if tgt in biz_modules and src in biz_modules and src != tgt:
            callers.setdefault(tgt, set()).add(src)
    denom = len(biz_modules) - 1
    return {mod: len(callers.get(mod, ())) / denom for mod in biz_modules}


def _detect_infra_modules(
    biz_modules: list[tuple[str, str]],
    module_paths: dict[str, str],
    edges: list[tuple[tuple[str, str], tuple[str, str], int]],
    *,
    path_patterns: list[str],
    fan_in_threshold: float = 0.5,
) -> set[tuple[str, str]]:
    """Identify shared infrastructure modules by path, fan-in, or naming heuristics."""
    if not isinstance(path_patterns, list):
        path_patterns = []
    if not isinstance(fan_in_threshold, (int, float)):
        fan_in_threshold = 0.5
    mod_set = set(biz_modules)
    fan_in = _compute_module_fan_in_ratios(mod_set, edges)
    infra: set[tuple[str, str]] = set()

    for repo, name in biz_modules:
        compound = _compound_key(repo, name)
        path = module_paths.get(compound, module_paths.get(name, ""))
        if _is_infra_module_path(path, path_patterns):
            infra.add((repo, name))
            continue
        if (
            len(mod_set) >= _FAN_IN_MIN_MODULE_COUNT
            and fan_in.get((repo, name), 0.0) >= fan_in_threshold
        ):
            infra.add((repo, name))
            continue
        if _is_abstract_module_name(name):
            infra.add((repo, name))
            continue
        if _PASCAL_CASE_RE.match(name) and (
            name.endswith(_INFRA_CLASS_SUFFIXES) or _is_infra_handler(name)
        ):
            infra.add((repo, name))

    return infra


def _reassign_infra_modules(
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
    infra_modules: set[tuple[str, str]],
    infrastructure_label: str,
) -> None:
    """Move infrastructure modules into a dedicated domain bucket."""
    if not infra_modules:
        return

    label = infrastructure_label if isinstance(infrastructure_label, str) else "__infrastructure__"
    infra_slug = normalize_slug(label.strip() or "__infrastructure__")
    for slug in list(domain_mapping.keys()):
        domain_mapping[slug] = [m for m in domain_mapping[slug] if m not in infra_modules]
        if not domain_mapping[slug]:
            del domain_mapping[slug]

    domain_mapping.setdefault(infra_slug, [])
    existing = set(domain_mapping[infra_slug])
    for mod in sorted(infra_modules):
        if mod not in existing:
            domain_mapping[infra_slug].append(mod)
            existing.add(mod)

    domain_display_names.setdefault(infra_slug, label)
    log.info(
        "infra_modules_reassigned",
        infra_slug=infra_slug,
        module_count=len(infra_modules),
    )


def _is_infra_slug(
    slug: str,
    modules: list[tuple[str, str]],
    infrastructure_keywords: list[str],
) -> bool:
    """Return True if slug/modules match infrastructure domain heuristics."""
    if len(modules) == 1:
        _, name = modules[0]
        if _PASCAL_CASE_RE.match(name) and (
            name.endswith(_INFRA_CLASS_SUFFIXES) or _is_infra_handler(name)
        ):
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
    """Remove infrastructure sub-domains without merging into siblings."""
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

    # Don't merge infra modules into business siblings - just drop them.
    # They will be handled by Step 6.54's per-module infrastructure reassignment.
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


def _build_tree_review_prompt(tree: list[dict]) -> str:
    """Build a prompt for LLM to review tree structure and propose reparents."""
    lines = ["Review this domain tree for hierarchy consistency issues.", ""]
    lines.append("Current tree structure:")

    def _format_node(node: dict, indent: int = 0) -> None:
        prefix = "  " * indent
        name = node.get("name", "?")
        display = node.get("display_name", "")
        modules_count = len(node.get("modules") or [])
        lines.append(f"{prefix}- {name} ({display}) [{modules_count} modules]")
        for child in node.get("children") or []:
            _format_node(child, indent + 1)

    for node in tree:
        _format_node(node)

    lines.append("")
    lines.append("Rules:")
    lines.append("- Domains with the same business prefix (e.g. intimacy-*, family-*) should be in the same subtree")
    lines.append("- L1 nodes that share a prefix with nested children of a shell node should be reparented")
    lines.append("- Only propose moves that improve hierarchy consistency")
    lines.append("")
    lines.append('Respond in JSON: {"reparents": [{"child": "slug", "new_parent": "slug or null for L1", "reason": "..."}]}')
    lines.append('If no reparent needed, respond: {"reparents": []}')

    return "\n".join(lines)


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


def _is_shell_section(node: dict) -> bool:
    """True when node is a container shell: no modules, no overview, only subsection children."""
    if node.get("has_overview"):
        return False
    modules = node.get("modules") or []
    children = node.get("children") or []
    return not modules and bool(children)


def _collapse_empty_shells(tree: list[dict]) -> list[dict]:
    """Collapse shell domains (0 modules, no overview) by promoting children to parent."""

    def _collapse_node(node: dict) -> list[dict]:
        children = node.get("children") or []
        if children:
            expanded: list[dict] = []
            for child in children:
                expanded.extend(_collapse_node(child))
            node = {**node, "children": expanded}

        if _is_shell_section(node):
            shell_name = node.get("name", "")
            promoted: list[dict] = []
            for child in node.get("children") or []:
                collapsed_from = list(child.get("collapsed_from", []))
                if shell_name:
                    collapsed_from.append(shell_name)
                child["collapsed_from"] = collapsed_from
                promoted.append(child)
            return promoted
        return [node]

    result: list[dict] = []
    for n in tree:
        result.extend(_collapse_node(n))
    return result


_MAX_SLUG_SEGMENTS = 5
_MAX_SLUG_LENGTH = 40


def _is_low_quality_slug(slug: str) -> bool:
    """Detect garbage slugs: too long, truncated, or lacking business semantics."""
    parts = slug.split("-")
    if len(parts) > _MAX_SLUG_SEGMENTS:
        return True
    if len(slug) > _MAX_SLUG_LENGTH:
        return True
    if any(len(p) > 15 for p in parts):
        return True
    if re.search(r"[a-z]{3,}[A-Z]", slug):
        return True
    return False


def _fix_low_quality_slug(result: dict) -> dict:
    """Replace garbage slugs with display-name-based sanitized slug."""
    slug = result.get("slug", "")
    if not slug or not _is_low_quality_slug(slug):
        return result
    display_name = result.get("display_name", "")
    log.warning("low_quality_slug_detected", slug=slug, display_name=display_name)
    sanitized = normalize_slug(display_name) if display_name else ""
    if sanitized and sanitized != "unnamed" and not _is_low_quality_slug(sanitized):
        result["slug"] = sanitized
        log.info("low_quality_slug_sanitized", original=slug, sanitized=sanitized)
        return result
    parts = slug.split("-")[:_MAX_SLUG_SEGMENTS]
    trimmed = "-".join(p[:15] for p in parts)[:_MAX_SLUG_LENGTH].strip("-")
    result["slug"] = trimmed or "unnamed-domain"
    log.info("low_quality_slug_trimmed", original=slug, trimmed=result["slug"])
    return result


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
    (("intimacy", "亲密"), ("user-behavior", "behavior-stat", "用户行为")),
    (("intimacy", "亲密"), ("family", "家族", "guild")),
    (("family", "家族"), ("intimacy", "亲密")),
    (("user-growth", "用户成长"), ("family", "家族")),
    (("user-growth", "用户成长"), ("relation", "关系")),
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


def _reparent_infra_misplaced_to_root(
    domain_tree: list[dict],
    infrastructure_keywords: list[str],
) -> list[dict[str, str]]:
    """Promote infra slugs nested under business domains to tree root."""
    reparented: list[dict[str, str]] = []

    def _walk(nodes: list[dict]) -> None:
        for node in nodes:
            children = list(node.get("children") or [])
            if not children:
                continue
            parent_slug = node.get("name", "")
            parent_is_business = not _is_infra_slug(
                parent_slug, node.get("modules") or [], infrastructure_keywords,
            )
            kept: list[dict] = []
            for child in children:
                child_slug = child.get("name", "")
                if parent_is_business and _is_infra_slug(
                    child_slug, child.get("modules") or [], infrastructure_keywords,
                ):
                    reparented.append({
                        "child": child_slug,
                        "parent": parent_slug,
                        "reason": "infrastructure domain nested under business domain",
                    })
                    domain_tree.append(child)
                    log.warning(
                        "infra_misplaced_reparent",
                        child=child_slug,
                        parent=parent_slug,
                    )
                else:
                    kept.append(child)
            node["children"] = kept
            _walk(kept)

    _walk(domain_tree)
    return reparented


def _review_subdomain_placement(
    domain_tree: list[dict],
    embeddings: dict[str, list[float]] | None = None,
    *,
    infrastructure_keywords: list[str] | None = None,
) -> list[dict[str, str]]:
    """Review sub-domain placement; reparent mismatched nodes to tree root."""
    del embeddings  # reserved for future embedding-based checks
    keywords = infrastructure_keywords
    if keywords is None:
        keywords = get_settings().wiki.infrastructure_slug_keywords

    if keywords:
        _reparent_infra_misplaced_to_root(domain_tree, keywords)

    reparented: list[dict[str, str]] = []

    def _walk(nodes: list[dict]) -> None:
        for node in nodes:
            children = list(node.get("children") or [])
            if not children:
                continue
            parent_slug = node.get("name", "")
            parent_display = node.get("display_name", "")
            kept: list[dict] = []
            for child in children:
                child_slug = child.get("name", "")
                child_display = child.get("display_name", "")
                if child.get("user_modified"):
                    kept.append(child)
                    continue
                if _slug_semantically_mismatched(parent_slug, child_slug):
                    reparented.append({
                        "child": child_slug,
                        "parent": parent_slug,
                        "reason": (
                            f"'{child_display}' semantically mismatched with parent '{parent_display}'"
                        ),
                    })
                    domain_tree.append(child)
                    log.warning(
                        "subdomain_placement_reparent",
                        child=child_slug,
                        parent=parent_slug,
                    )
                else:
                    kept.append(child)
            node["children"] = kept
            _walk(kept)

    _walk(domain_tree)
    return reparented


def _dedupe_slug_segments(slug: str) -> str:
    """Remove consecutive repeated multi-word segments: a-b-b → a-b, x-y-z-y-z → x-y-z."""
    parts = slug.split("-")
    if not parts:
        return slug
    result = [parts[0]]
    i = 1
    while i < len(parts):
        for seg_len in range(1, len(parts) - i + 1):
            if i + seg_len <= len(parts) and parts[i : i + seg_len] == result[-seg_len:]:
                i += seg_len
                break
        else:
            result.append(parts[i])
            i += 1
    return "-".join(result)


def _dedup_parallel_naming_results(
    results: list[dict],
    existing_slugs: list[str],
) -> list[dict]:
    """Deduplicate slugs after parallel LLM naming — merge-first strategy."""
    if not results:
        return results

    # Pass 1: Merge exact slug duplicates
    by_slug: dict[str, dict] = {}
    for result in results:
        slug = result["slug"]
        if slug in by_slug:
            by_slug[slug]["modules"] = list(by_slug[slug].get("modules", [])) + list(result.get("modules", []))
        else:
            by_slug[slug] = dict(result)
    merged = list(by_slug.values())

    # Pass 2: Merge stem-suffix pairs (e.g., "foo" absorbs "foo-service", "foo-system")
    # Skip numeric suffixes (-2, -3) which are disambiguation markers, not semantic extensions
    _NUMERIC_SUFFIX_RE = re.compile(r"-\d+$")
    slugs_sorted = sorted(by_slug.keys(), key=len)
    merge_map: dict[str, str] = {}
    for i, shorter in enumerate(slugs_sorted):
        for longer in slugs_sorted[i + 1 :]:
            if longer.startswith(shorter + "-") and longer not in merge_map:
                suffix = longer[len(shorter) + 1 :]
                if _NUMERIC_SUFFIX_RE.match("-" + suffix):
                    continue
                merge_map[longer] = shorter

    if merge_map:
        final_merged: dict[str, dict] = {}
        for entry in merged:
            slug = entry["slug"]
            target = merge_map.get(slug, slug)
            if target in final_merged:
                final_merged[target]["modules"] = list(final_merged[target].get("modules", [])) + list(
                    entry.get("modules", [])
                )
            else:
                if target != slug:
                    entry["slug"] = target
                final_merged[target] = entry
        merged = list(final_merged.values())

    # Pass 3: Resolve collisions with existing_slugs
    seen: set[str] = set(existing_slugs)
    for entry in merged:
        slug = entry["slug"]
        if slug in seen:
            counter = 2
            while f"{slug}-{counter}" in seen:
                counter += 1
            new_slug = f"{slug}-{counter}"
            log.warning("slug_collision_resolved", original=slug, resolved=new_slug)
            entry["slug"] = new_slug
        seen.add(entry["slug"])

    # Final cleanup
    for entry in merged:
        entry["slug"] = _dedupe_slug_segments(entry["slug"])
        _fix_low_quality_slug(entry)
    return merged


def _merge_sub_domain_entries(primary: dict, secondary: dict) -> None:
    """Combine modules and children from secondary into primary."""
    primary["modules"] = list(primary.get("modules", [])) + list(secondary.get("modules", []))
    sec_children = secondary.get("children") or []
    if sec_children:
        primary.setdefault("children", []).extend(sec_children)


def _dedup_sub_domains(
    named_subs: list[dict],
    parent_display_name: str,
    ancestor_display_names: set[str] | None = None,
) -> list[dict]:
    """Merge sub-domains with identical display_name, dedup slugs, avoid parent/ancestor collision."""
    merged_by_name: dict[str, dict] = {}
    for sub in named_subs:
        display = sub.get("display_name", "").strip()
        key = display or sub.get("slug", f"unnamed-{len(merged_by_name)}")
        if key in merged_by_name:
            existing = merged_by_name[key]
            if len(sub.get("modules", [])) > len(existing.get("modules", [])):
                merged = dict(sub)
                _merge_sub_domain_entries(merged, existing)
                merged_by_name[key] = merged
            else:
                _merge_sub_domain_entries(existing, sub)
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


def _build_pinned_domains_for_clustering(
    pinned_modules: dict[str, str],
    biz_modules: list[tuple[str, str]],
) -> dict[tuple[str, str], str] | None:
    """Convert state pinned_modules (repo|name or bare name → slug) to clusterer tuple keys."""
    if not pinned_modules:
        return None
    pinned_domains: dict[tuple[str, str], str] = {}
    for key, domain_slug in pinned_modules.items():
        pin_repo, mod_name = _split_pinned_module_key(key)
        if pin_repo:
            pinned_domains[(pin_repo, mod_name)] = domain_slug
            continue
        for repo, name in biz_modules:
            if name == mod_name:
                pinned_domains[(repo, name)] = domain_slug
    return pinned_domains or None


async def _embedding_clustering(
    biz_modules: list[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    module_paths: dict[str, str],
    module_summaries_raw: dict[str, dict[str, Any]],
    embedding_cache: dict[str, list[float]] | None = None,
    pinned_domains: dict[tuple[str, str], str] | None = None,
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

    from wiki.graph_centrality import compute_hub_weights

    wiki_cfg = get_settings().wiki
    hub_weights = compute_hub_weights(biz_modules, edges)
    clusterer = DomainSemanticClusterer()
    communities = clusterer.cluster(
        embeddings,
        biz_modules,
        edges,
        paths=module_paths,
        pinned_domains=pinned_domains,
        enable_prefix_cannot_link=wiki_cfg.enable_prefix_cannot_link,
        prefix_penalty_factor=wiki_cfg.cluster_prefix_penalty_factor,
        hub_weights=hub_weights or None,
    )
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


def _build_module_embedding_lookup(
    biz_modules: list[tuple[str, str]],
    embedding_cache: dict[str, list[float]],
    module_summaries_raw: dict[str, dict[str, Any]],
    module_paths: dict[str, str],
) -> dict[tuple[str, str], list[float]]:
    """Build (repo, mod_name) -> embedding vector lookup from the SHA-256-keyed cache."""
    from wiki.domain_semantic_clusterer import DomainSemanticClusterer

    texts = DomainSemanticClusterer.build_embedding_texts(
        biz_modules, module_summaries_raw or {}, module_paths,
    )
    lookup: dict[tuple[str, str], list[float]] = {}
    for mod_key, text in zip(biz_modules, texts, strict=True):
        cache_key = _embedding_text_hash(text)
        emb = embedding_cache.get(cache_key)
        if emb is not None:
            lookup[mod_key] = emb
    return lookup


def _assign_new_modules_to_nearest(
    new_modules: set[tuple[str, str]],
    domain_mapping: dict[str, list[tuple[str, str]]],
    mod_embeddings: dict[tuple[str, str], list[float]],
) -> None:
    """Assign new modules to the semantically nearest existing domain.

    ``mod_embeddings`` maps ``(repo, mod_name)`` to embedding vectors.
    Modifies domain_mapping in place.
    """
    if not new_modules or not domain_mapping:
        return

    domain_centroids: dict[str, Any] = {}
    for slug, pairs in domain_mapping.items():
        vecs = []
        for pair in pairs:
            emb = mod_embeddings.get(pair)
            if emb is not None:
                vecs.append(np.array(emb, dtype=np.float32))
        if vecs:
            domain_centroids[slug] = np.mean(vecs, axis=0)

    if not domain_centroids:
        return

    for mod_key in new_modules:
        emb = mod_embeddings.get(mod_key)
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
            domain_mapping[best_slug].append(mod_key)
            log.info("new_module_assigned", module=mod_key, domain=best_slug, similarity=round(best_sim, 3))


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
    naming_cache: dict[str, dict[str, str]] = dict(state.get("naming_cache") or {})
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
        pinned_domains = None
        wiki_cfg = get_settings().wiki
        if wiki_cfg.enable_anchor_cluster_constraints and pinned_modules:
            pinned_domains = _build_pinned_domains_for_clustering(pinned_modules, biz_modules)
        communities, embeddings = await _embedding_clustering(
            biz_modules, edges, module_paths, module_summaries_raw,
            embedding_cache=embedding_cache,
            pinned_domains=pinned_domains,
        )

        # --- Step 3: LLM Naming with module_infos (parallelized) ---
        project_docs = configurable.get("project_docs", [])
        namer = GraphDomainNamer(llm, project_docs=project_docs, naming_cache=naming_cache)
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
                    "repository": repo_id,
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
        # Load anchors if available (incremental protection only)
        anchor_service = state.get("anchor_service")
        anchored_slugs: frozenset[str] = frozenset(state.get("anchored_slugs") or set())
        if anchor_service:
            try:
                anchors = await anchor_service.get_anchors(state.get("business_id", ""))
                anchored_slugs = anchored_slugs | frozenset(a.slug for a in anchors)
            except Exception:
                log.warning("anchor_load_failed", exc_info=True)

        # After clustering and naming, verify anchored domains survived
        if anchored_slugs and communities_named:
            result_slugs = {r["slug"] for r in communities_named}
            missing = anchored_slugs - result_slugs
            for slug in missing:
                log.warning("anchored_domain_missing_after_cluster", slug=slug)

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

        paths_for_corrector = _build_paths_for_corrector(biz_modules, module_paths)
        package_tree_str = _build_package_tree(paths_for_corrector)
        cross_domain_edges_str = _build_cross_domain_edges_summary(edges, domain_mapping)
        reviewer = DomainReviewAgent(llm=llm, max_move_ratio=0.5)
        domain_mapping, domain_display_names = await reviewer.review(
            domain_mapping, domain_display_names, paths_for_corrector, module_summaries_flat,
            business_id=state.get("business_id", ""),
            module_details=module_summaries_raw,
            language=_resolve_content_language(state),
            anchored_slugs=anchored_slugs,
            package_tree_str=package_tree_str,
            cross_domain_edges_str=cross_domain_edges_str,
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
                    mod_emb_lookup = _build_module_embedding_lookup(
                        biz_modules, embedding_cache, module_summaries_raw, module_paths,
                    )
                    _assign_new_modules_to_nearest(new_mods, domain_mapping, mod_emb_lookup)
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

        # --- Step 6.54: Per-module infrastructure reassignment ---
        wiki_cfg = get_settings().wiki
        infra_modules = _detect_infra_modules(
            biz_modules,
            module_paths,
            edges,
            path_patterns=wiki_cfg.infra_module_patterns,
            fan_in_threshold=wiki_cfg.infra_module_fan_in_threshold,
        )
        if infra_modules:
            infra_label = wiki_cfg.business_domain_infrastructure_label
            if not isinstance(infra_label, str) or not infra_label.strip():
                infra_label = "__infrastructure__"
            _reassign_infra_modules(
                domain_mapping,
                domain_display_names,
                infra_modules,
                infra_label,
            )

        # --- Step 6.55: Infrastructure domain filtering ---
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
                sub_paths = _build_paths_for_corrector(sub_modules, module_paths)
                sub_clusters = clusterer.cluster_sub_domains(
                    sub_embeddings, sub_modules, edges, paths=sub_paths
                )
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
                        "repository": repo_id,
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

            def _cluster_from_module_keys(module_keys: list[str]) -> set[tuple[str, str]]:
                cluster: set[tuple[str, str]] = set()
                for key in module_keys:
                    repo_id, mod_name = key.split(".", 1)
                    cluster.add((repo_id, mod_name))
                return cluster

            named_subs: list[dict] = []
            sub_tasks = [
                _build_named_sub(sub_naming, _cluster_from_module_keys(sub_naming.get("modules", [])))
                for sub_naming in deduped_results
            ]
            if len(sub_tasks) > 1:
                sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)
                for sub_result in sub_results:
                    if isinstance(sub_result, dict):
                        named_subs.append(sub_result)
                    elif isinstance(sub_result, BaseException):
                        log.warning("sub_domain_recursive_split_failed", exc_info=sub_result)
            elif sub_tasks:
                named_subs.append(await sub_tasks[0])

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

    # --- Step 8.5: Theme aggregation (F10) ---
    wiki_cfg = get_settings().wiki
    if llm and domain_tree and len(domain_tree) > wiki_cfg.theme_aggregation_min_domains:
        from wiki.domain_merger import aggregate_domains_recursive

        domain_tree = await aggregate_domains_recursive(
            domain_tree,
            llm,
            min_siblings=2,
        )
        log.info("theme_aggregation_applied", l1_count=len(domain_tree))

    if domain_tree:
        from wiki.prefix_family_grouper import enforce_prefix_family_grouping

        domain_tree = enforce_prefix_family_grouping(domain_tree)

    # --- Step 8.6: DomainReviewAgent tree-level review ---
    if wiki_cfg.enable_domain_tree_review and domain_tree and llm:
        try:
            from wiki.json_robust import parse_json_robust_sync
            from wiki.prompts import SYSTEM_JSON_ONLY

            module_summaries_flat = _build_module_summaries_flat_for_corrector(
                biz_modules, module_summaries_raw,
            )
            tree_reviewer = DomainReviewAgent(llm=llm)
            tree_reviewer.set_tree_data(
                domain_tree,
                domain_display_names,
                module_summaries_flat,
            )

            tree_prompt = _build_tree_review_prompt(domain_tree)
            await acquire_llm_quota(config, estimated_tokens=2000)
            raw_content = await llm.generate(tree_prompt, system=SYSTEM_JSON_ONLY)
            decisions = parse_json_robust_sync(raw_content)

            _MAX_TREE_REPARENTS = 3
            if isinstance(decisions, dict):
                proposed = 0
                for reparent in decisions.get("reparents", []):
                    if proposed >= _MAX_TREE_REPARENTS:
                        break
                    child = reparent.get("child")
                    new_parent = reparent.get("new_parent")
                    reason = reparent.get("reason", "")
                    if not child:
                        continue
                    # Skip if child was placed by C3 deterministic grouping (user_modified)
                    child_node = tree_reviewer._find_node_in_tree(child)
                    if child_node and child_node.get("user_modified"):
                        continue
                    tree_reviewer._propose_reparent_domain(child, new_parent, reason)
                    proposed += 1

                if tree_reviewer.pending_tree_reparents:
                    reparent_count = len(tree_reviewer.pending_tree_reparents)
                    domain_tree = tree_reviewer.apply_tree_decisions()
                    log.info("domain_review_tree_reparent", count=reparent_count)
        except Exception as e:
            log.warning("domain_review_tree_failed", error=str(e))

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

    result: dict[str, Any] = {
        "domain_mapping": domain_mapping,
        "domain_display_names": domain_display_names,
        "domain_tree": domain_tree,
        "affected_domains": affected_domains,
        "module_call_edges": module_call_edges,
        "embedding_cache": embedding_cache,
        "naming_cache": naming_cache,
        "term_glossary": term_glossary,
    }
    if state.get("decomposition_warnings"):
        result["decomposition_warnings"] = state["decomposition_warnings"]
    return result
