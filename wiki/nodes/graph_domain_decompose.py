"""Graph-driven domain decomposition node for wiki pipeline."""

import asyncio
import hashlib
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
        + "\n\nReturn JSON: {\"merge_groups\": [[\"slugA\", \"slugB\"], ...]}. "
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
        result = await llm.complete_json(messages, {})
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
_MAX_SPLIT_DEPTH = 3


def _sub_to_tree_node(sub: dict) -> dict[str, Any]:
    """Convert a recursive sub-domain dict into a domain_tree node."""
    children_raw = sub.get("children", [])
    children = [_sub_to_tree_node(c) for c in children_raw]
    if children:
        return {
            "name": sub.get("slug", ""),
            "display_name": sub.get("display_name", ""),
            "modules": [],
            "children": children,
        }
    mod_keys = [_compound_key(repo, name) for repo, name in sub.get("modules", [])]
    return {
        "name": sub.get("slug", ""),
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
            children = [_sub_to_tree_node(s) for s in sub]
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


def _dedup_parallel_naming_results(
    results: list[dict],
    existing_slugs: list[str],
) -> list[dict]:
    """Deduplicate slugs after parallel LLM naming."""
    seen: set[str] = set(existing_slugs)
    for result in results:
        slug = result["slug"]
        if slug in seen:
            suffix = hashlib.md5(str(result).encode()).hexdigest()[:4]
            new_slug = f"{slug}-{suffix}"
            log.warning("slug_collision_resolved", original=slug, resolved=new_slug)
            result["slug"] = new_slug
        seen.add(result["slug"])
    return results


def _dedup_sub_domains(
    named_subs: list[dict],
    parent_display_name: str,
) -> list[dict]:
    """Merge sub-domains with identical display_name, dedup slugs, avoid parent-child collision."""
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

    for sub in result:
        if sub["display_name"] == parent_display_name:
            sub["display_name"] = f"{sub['display_name']}（核心）"

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
        )

        # Rebuild communities_named after review
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
        ) -> list[dict]:
            if len(community_modules) <= _SPLIT_THRESHOLD or depth >= _MAX_SPLIT_DEPTH:
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
                    community_set, edges, max_depth=2, max_leaf_size=_SPLIT_THRESHOLD,
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
                children = await _recursive_split(
                    list(sub_cluster),
                    list(all_slugs),
                    sub_naming["display_name"],
                    depth + 1,
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

            named_subs = _dedup_sub_domains(named_subs, parent_display)
            return named_subs

        for c in communities_named:
            slug = c["slug"]
            community_modules = list(c["modules"])
            parent_display = domain_display_names.get(slug, slug)
            subs = await _recursive_split(community_modules, used_names, parent_display, 0)
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
        domain_tree = _build_domain_tree(communities_named, sub_trees)

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

    return {
        "domain_mapping": domain_mapping,
        "domain_display_names": domain_display_names,
        "domain_tree": domain_tree,
        "affected_domains": affected_domains,
        "module_call_edges": module_call_edges,
        "embedding_cache": embedding_cache,
    }
