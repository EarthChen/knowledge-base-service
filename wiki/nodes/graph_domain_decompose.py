"""Graph-driven domain decomposition node for wiki pipeline."""

import asyncio
import hashlib
from typing import Any

import numpy as np
from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.domain_semantic_clusterer import DomainSemanticClusterer
from wiki.entity_role_classifier import DOMAIN_CLASSIFICATION_ENTITY_ROLES
from wiki.graph_call_query import fetch_module_call_edges
from wiki.graph_domain_namer import GraphDomainNamer
from wiki.graph_semantic_corrector import GraphSemanticCorrector
from wiki.nodes.classify import (
    _consolidate_split_entities,
    _ensure_ascii_keys,
    classify_domains_node,
    decompose_hierarchy_node,
)
from wiki.pipeline_concurrency import PipelineConcurrency

log = get_logger(__name__)

# Copied from classify_domains_node for consistency
_DATA_MODEL_NAME_SUFFIXES = (
    "DTO", "Dto", "VO", "Vo", "Req", "Resp", "Request", "Response",
    "Param", "Form", "Query", "Result", "Enum", "Constants", "Entity",
    "Bo", "PO", "Po", "Config",
)
_DATA_MODEL_PATH_MARKERS = ("/dto/", "/model/", "/entity/", "/enums/", "/config/")


def _is_data_model(name: str, path: str) -> bool:
    if any(name.endswith(suffix) for suffix in _DATA_MODEL_NAME_SUFFIXES):
        return True
    if any(marker in path.lower() for marker in _DATA_MODEL_PATH_MARKERS):
        return True
    return False


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
    similarity_threshold: float = 0.8,
) -> tuple[dict[str, list], dict[str, str]]:
    """Fallback: merge domains whose display_name embeddings exceed similarity threshold."""
    from numpy import dot
    from numpy.linalg import norm

    from core.config import get_settings
    from indexer.embedding_generator import EmbeddingGenerator

    slugs = list(domain_display_names.keys())
    names = [domain_display_names[s] for s in slugs]
    if len(names) <= 2:
        return domain_mapping, domain_display_names

    try:
        config = get_settings().embedding
        generator = EmbeddingGenerator.shared(config)
        embeddings = await generator.generate(names)
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
    mod_names = [name for _, name in sub.get("modules", [])]
    return {
        "name": sub.get("slug", ""),
        "display_name": sub.get("display_name", ""),
        "modules": mod_names,
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
            mod_names = [name for _, name in modules]
            tree.append({
                "name": slug,
                "display_name": display_name,
                "modules": mod_names,
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
) -> list[set[tuple[str, str]]]:
    """Fallback: use TF-IDF on module names+paths when embeddings are unavailable."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.feature_extraction.text import TfidfVectorizer

    n = len(biz_modules)
    if n < 3:
        return [set(biz_modules)]

    texts = [f"{name} {module_paths.get(name, '')}" for _, name in biz_modules]
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


async def _embedding_clustering(
    biz_modules: list[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    module_paths: dict[str, str],
    module_summaries_raw: dict[str, dict[str, Any]],
) -> tuple[list[set[tuple[str, str]]], np.ndarray | None]:
    """Primary: semantic embedding clustering. Returns (clusters, embeddings_array)."""
    from core.config import get_settings
    from indexer.embedding_generator import EmbeddingGenerator

    texts = DomainSemanticClusterer.build_embedding_texts(
        biz_modules, module_summaries_raw, module_paths,
    )

    try:
        config = get_settings().embedding
        generator = EmbeddingGenerator.shared(config)
        embedding_lists = await generator.generate(texts)
        embeddings = np.array(embedding_lists, dtype=np.float32)
    except Exception:
        log.warning("embedding_generation_failed_fallback_tfidf", exc_info=True)
        try:
            return _tfidf_fallback_clustering(biz_modules, module_paths, edges), None
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

    if graph_store is None:
        log.info("graph_domain_decompose_fallback", reason="no graph_store")
        classify_result = await classify_domains_node(state, config)
        state_with_classify = {**state, **classify_result}
        decompose_result = await decompose_hierarchy_node(state_with_classify, config)
        return {**classify_result, **decompose_result}

    # --- Step 0: Filter to BIZ modules ---
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})
    repositories = state.get("repositories", [])

    module_paths: dict[str, str] = {}
    module_docstrings: dict[str, str] = {}
    biz_modules: list[tuple[str, str]] = []
    for repo, mod_list in modules.items():
        for mod_dict in mod_list:
            uid = mod_dict.get("uid", "")
            props = mod_dict.get("properties", {})
            name = str(props.get("name", ""))
            path = str(props.get("path", "") or "")
            if name:
                module_paths[name] = path
                doc = str(props.get("business_summary", "") or props.get("docstring", "") or "")
                if doc:
                    module_docstrings[name] = doc
            if entity_roles.get(uid) not in DOMAIN_CLASSIFICATION_ENTITY_ROLES:
                continue
            if not name or path.startswith("<import:"):
                continue
            if _is_data_model(name, path):
                continue
            biz_modules.append((repo, name))

    if not biz_modules:
        return {
            "domain_mapping": {},
            "domain_display_names": {},
            "domain_tree": [],
            "affected_domains": [],
            "module_call_edges": [],
        }

    valid_modules_set = set(biz_modules)

    # --- Step 1: Fetch call graph edges ---
    edges, query_errors = await fetch_module_call_edges(graph_store, repositories, valid_modules_set)

    if query_errors:
        log.warning("graph_domain_decompose_query_errors", errors=query_errors)
    log.info("graph_domain_decompose_edges", total_modules=len(biz_modules), total_edges=len(edges))

    # --- Step 1.5: Collect module summaries from pipeline state ---
    module_summaries_raw: dict[str, dict[str, Any]] = state.get("module_summaries", {}) or {}

    # --- Step 2: Semantic embedding clustering (fallback: Louvain) ---
    communities, embeddings = await _embedding_clustering(
        biz_modules, edges, module_paths, module_summaries_raw,
    )

    # --- Step 3: LLM Naming with module_infos (parallelized) ---
    namer = GraphDomainNamer(llm)

    async def _name_community(community: set[tuple[str, str]]) -> dict[str, Any]:
        module_infos = []
        for repo_id, mod_name in sorted(community):
            summary_data = module_summaries_raw.get(mod_name)
            summary_text = ""
            if isinstance(summary_data, dict):
                summary_text = str(summary_data.get("summary_text", ""))
            elif isinstance(summary_data, str):
                summary_text = summary_data
            doc = module_docstrings.get(mod_name, "")
            if doc and doc not in summary_text:
                summary_text = f"[{doc}] {summary_text}" if summary_text else doc
            module_infos.append({
                "name": mod_name,
                "path": module_paths.get(mod_name, ""),
                "summary": summary_text,
            })
        naming = await namer.name_community(
            module_infos=module_infos,
            used_names=None,
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
    communities_named: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("domain_naming_task_failed", exc_info=r)
        elif isinstance(r, dict):
            communities_named.append(r)

    # Ensure unique slugs
    seen_slugs: set[str] = set()
    for c in communities_named:
        slug = c["slug"]
        if slug in seen_slugs:
            counter = 1
            while f"{slug}-{counter}" in seen_slugs:
                counter += 1
            c["slug"] = f"{slug}-{counter}"
        seen_slugs.add(c["slug"])

    used_names: list[str] = [c["slug"] for c in communities_named]

    # --- Step 4: Build domain_mapping ---
    domain_mapping: dict[str, list[tuple[str, str]]] = {}
    domain_display_names: dict[str, str] = {}
    for c in communities_named:
        domain_mapping[c["slug"]] = list(c["modules"])
        domain_display_names[c["slug"]] = c["display_name"]

    # --- Step 5: Post-processing (safety nets) ---
    domain_mapping, domain_display_names = _ensure_ascii_keys(domain_mapping, domain_display_names)
    domain_mapping, domain_display_names = _consolidate_split_entities(domain_mapping, domain_display_names)
    if llm:
        domain_mapping, domain_display_names = await _merge_domains_by_llm(
            domain_mapping, domain_display_names, llm,
        )
    else:
        domain_mapping, domain_display_names = await _merge_domains_by_embedding(
            domain_mapping, domain_display_names,
        )

    # --- Step 5.5: LLM Global Consistency Review ---
    module_summaries_flat: dict[str, str] = {}
    for mod_name, data in module_summaries_raw.items():
        if isinstance(data, dict):
            module_summaries_flat[mod_name] = str(data.get("summary_text", ""))
        elif isinstance(data, str):
            module_summaries_flat[mod_name] = data

    corrector = GraphSemanticCorrector(llm)
    domain_mapping, domain_display_names = await corrector.review_global_consistency(
        domain_mapping, domain_display_names, module_paths, module_summaries_flat,
        business_id=state.get("business_id", ""),
        module_details=module_summaries_raw,
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
    sub_trees: dict[str, list[dict]] = {}
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
                summary_data = module_summaries_raw.get(mod_name)
                summary_text = ""
                if isinstance(summary_data, dict):
                    summary_text = str(summary_data.get("summary_text", ""))
                elif isinstance(summary_data, str):
                    summary_text = summary_data
                doc = module_docstrings.get(mod_name, "")
                if doc and doc not in summary_text:
                    summary_text = f"[{doc}] {summary_text}" if summary_text else doc
                sub_infos.append({
                    "name": mod_name,
                    "path": module_paths.get(mod_name, ""),
                    "summary": summary_text,
                })
            async with sem:
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

        named_subs: list[dict] = []
        for sub_naming, sub_cluster in zip(deduped_results, valid_clusters, strict=True):
            children = await _recursive_split(
                list(sub_cluster), all_slugs, sub_naming["display_name"], depth + 1,
            )
            named_subs.append({
                "slug": sub_naming["slug"],
                "display_name": sub_naming["display_name"],
                "modules": list(sub_cluster),
                "children": children,
            })

        named_subs = _dedup_sub_domains(named_subs, parent_display)
        return named_subs

    for c in communities_named:
        slug = c["slug"]
        community_modules = list(c["modules"])
        parent_display = domain_display_names.get(slug, slug)
        subs = await _recursive_split(community_modules, used_names, parent_display, 0)
        if subs and len(subs) > 1:
            sub_trees[slug] = subs

    # --- Step 8: Build domain_tree ---
    domain_tree = _build_domain_tree(communities_named, sub_trees)

    # --- Step 9: Determine affected_domains ---
    affected_domains = list(domain_mapping.keys())

    log.info(
        "graph_domain_decompose_done",
        domains=len(domain_mapping),
        total_modules=sum(len(v) for v in domain_mapping.values()),
        with_sub_domains=len(sub_trees),
    )

    module_call_edges = [
        {"source": src[1], "target": dst[1], "weight": w}
        for src, dst, w in edges
    ]

    return {
        "domain_mapping": domain_mapping,
        "domain_display_names": domain_display_names,
        "domain_tree": domain_tree,
        "affected_domains": affected_domains,
        "module_call_edges": module_call_edges,
    }
