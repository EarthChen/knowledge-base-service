"""Pipeline nodes for graph-based wiki decomposition and bottom-up composition."""

import asyncio
import json
import warnings
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.llm_rate_limiter import acquire_llm_quota
from wiki.pipeline_concurrency import PipelineConcurrency

log = get_logger(__name__)

_LEAF_TIMEOUT_SEC = 120
_PARENT_TIMEOUT_SEC = 60

# Indexed code nodes use ``repository``, not ``repo_id``. Edges must be rolled up to
# :Module endpoints because CALLS/INHERITS/IMPLEMENTS/DEPENDS_ON usually attach to Function/Class.
_GRAPH_DECOMPOSE_MODULE_EDGES_CY = """
MATCH (ma:Module)-[:IMPORTS]->(mb:Module)
WHERE ma.repository = $repo AND mb.repository = $repo AND ma <> mb
RETURN ma.uid AS a_uid, mb.uid AS b_uid
UNION
MATCH (ma:Module)-[:CONTAINS*1..3]->(fa:Function)-[:CALLS]->(fb:Function)<-[:CONTAINS*1..3]-(mb:Module)
WHERE ma.repository = $repo AND mb.repository = $repo AND ma <> mb
RETURN ma.uid AS a_uid, mb.uid AS b_uid
UNION
MATCH (ma:Module)-[:CONTAINS*1..2]->(ca:Class)-[:DEPENDS_ON]->(cb:Class)<-[:CONTAINS*1..2]-(mb:Module)
WHERE ma.repository = $repo AND mb.repository = $repo AND ma <> mb
RETURN ma.uid AS a_uid, mb.uid AS b_uid
UNION
MATCH (ma:Module)-[:CONTAINS*1..2]->(ca:Class)-[:INHERITS]->(cb:Class)<-[:CONTAINS*1..2]-(mb:Module)
WHERE ma.repository = $repo AND mb.repository = $repo AND ma <> mb
RETURN ma.uid AS a_uid, mb.uid AS b_uid
UNION
MATCH (ma:Module)-[:CONTAINS*1..2]->(ca:Class)-[:IMPLEMENTS]->(cb:Class)<-[:CONTAINS*1..2]-(mb:Module)
WHERE ma.repository = $repo AND mb.repository = $repo AND ma <> mb
RETURN ma.uid AS a_uid, mb.uid AS b_uid
""".strip()


async def graph_decompose_node(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Build module tree from dependency graph using SCC + topological sort."""
    if state.get("is_incremental") and not state.get("affected_modules"):
        log.info("graph_decompose_skipped", reason="incremental_no_affected_modules")
        return {}

    from wiki.graph_module_decomposer import GraphModuleDecomposer

    configurable = (config or {}).get("configurable", {}) or {}
    graph_store = configurable.get("graph_store")

    modules = state.get("modules", {})
    nodes: list[str] = []
    node_files: dict[str, list[str]] = {}
    node_tokens: dict[str, int] = {}

    for _repo, mod_list in modules.items():
        for mod in mod_list:
            props = mod.get("properties", {})
            uid = (mod.get("uid") or "").strip()
            if not uid:
                continue
            fp = props.get("path") or props.get("file_path") or ""
            if fp.startswith("<import:"):
                continue
            nodes.append(uid)
            node_files[uid] = [fp] if fp else []
            token_est = int(props.get("code_length", 0) or 0)
            if not token_est:
                doc = props.get("docstring") or ""
                imports = props.get("imports") or []
                token_est = len(doc) + sum(len(i) for i in imports) if isinstance(imports, list) else len(doc)
            node_tokens[uid] = max(token_est // 4, 50)

    edge_pairs: set[tuple[str, str]] = set()
    if graph_store:
        node_set = set(nodes)
        for repo in state.get("repositories", []):
            try:
                result = await graph_store.execute_query(
                    _GRAPH_DECOMPOSE_MODULE_EDGES_CY,
                    {"repo": repo},
                )
                for row in getattr(result, "data", []) or []:
                    a = str(row.get("a_uid") or "").strip()
                    b = str(row.get("b_uid") or "").strip()
                    if a and b and a in node_set and b in node_set and a != b:
                        edge_pairs.add((a, b))
            except Exception:
                log.warning("graph_decompose_query_failed", repo=repo, exc_info=True)

    edges = sorted(edge_pairs)

    llm = configurable.get("llm")
    decomposer = GraphModuleDecomposer(llm=llm)
    repo_id = state.get("business_id", "")

    log.info(
        "graph_decompose_input",
        node_count=len(nodes),
        edge_count=len(edges),
        has_llm=llm is not None,
    )

    tree = await decomposer.decompose_from_graph(
        nodes, edges, node_files, node_tokens, repo_id,
    )

    log.info(
        "graph_decompose_result",
        tree_roots=len(tree.roots),
        tree_nodes=len(tree.all_nodes()),
        sample_keys=[n.canonical_key for n in tree.roots[:5]],
    )

    return {"module_tree": tree.to_dicts()}


async def assign_canonical_keys_node(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Populate canonical_keys mapping from module_tree."""
    from wiki.models.module_tree import ModuleTree

    _ = config
    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    canonical_keys: dict[str, str] = {}
    for node in tree.all_nodes():
        canonical_keys[node.canonical_key] = node.title or node.canonical_key
    return {"canonical_keys": canonical_keys}


async def generate_titles_node(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Generate human-readable titles for each module node via LLM."""
    from wiki.models.module_tree import ModuleTree

    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    budget_resolver = configurable.get("budget_resolver")

    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    canonical_keys = dict(state.get("canonical_keys", {}))

    nodes_needing_llm: list[Any] = []
    for node in tree.all_nodes():
        if node.title:
            canonical_keys[node.canonical_key] = node.title
            continue
        if node.file_paths:
            node.title = node.file_paths[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            canonical_keys[node.canonical_key] = node.title
        elif len(node.entity_uids) == 1:
            node.title = node.entity_uids[0]
            canonical_keys[node.canonical_key] = node.title
        elif llm:
            nodes_needing_llm.append(node)
        else:
            node.title = node.canonical_key
            canonical_keys[node.canonical_key] = node.title

    if nodes_needing_llm and llm:
        log.info("generate_titles_llm", count=len(nodes_needing_llm))
        sem = PipelineConcurrency.semaphore("bottomup")

        async def _gen_title(n: Any) -> tuple[Any, str, str]:
            async with sem:
                entity_names = ", ".join(n.entity_uids[:10])
                prompt = (
                    f"为代码模块生成一个简洁标题。\n"
                    f"模块key: {n.canonical_key}\n"
                    f"代码实体: {entity_names}\n"
                    f'输出JSON: {{"title": "标题", "description": "描述"}}'
                )
                try:
                    from wiki.token_budget import resolve_max_tokens

                    title_tokens = resolve_max_tokens(budget_resolver, "title_generation", default=200)
                    await acquire_llm_quota(config, estimated_tokens=title_tokens)
                    raw_text = await llm.generate(prompt, max_tokens=title_tokens)
                    data = json.loads(raw_text) if raw_text else {}
                    return n, data.get("title", n.canonical_key), data.get("description", "")
                except Exception:
                    return n, n.canonical_key, ""

        results = await asyncio.gather(
            *[_gen_title(n) for n in nodes_needing_llm],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                continue
            n, t, d = r
            n.title = t
            n.description = d
            canonical_keys[n.canonical_key] = t

    return {
        "module_tree": tree.to_dicts(),
        "canonical_keys": canonical_keys,
    }


async def compose_bottomup_node(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Bottom-up generation: leaves first via LLM, parents via ParentSynthesizer."""
    warnings.warn(
        "compose_bottomup_node is deprecated. "
        "Set USE_AGENT_COMPOSE=true to use compose_domain_agents_node.",
        DeprecationWarning,
        stacklevel=2,
    )
    from wiki.models.module_tree import ModuleTree

    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")
    budget_resolver = configurable.get("budget_resolver")
    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    domain_cache = dict(state.get("domain_cache", {}))

    log.info(
        "compose_bottomup_start",
        tree_roots=len(tree.roots),
        tree_nodes=len(tree.all_nodes()),
        has_llm=llm is not None,
        existing_pages=len(state.get("pages", [])),
        config_is_none=config is None,
        configurable_keys=list(configurable.keys()) if configurable else [],
    )

    raw_summaries = state.get("module_summaries", {})
    pages: list[dict[str, Any]] = list(state.get("pages", []))
    node_contents: dict[str, str] = {}

    # Build uid→name mapping from modules state so we can match summaries
    # (summaries are keyed by name, but tree entity_uids are full UIDs)
    uid_to_name: dict[str, str] = {}
    for _repo, mod_list in state.get("modules", {}).items():
        for mod in mod_list:
            uid = (mod.get("uid") or "").strip()
            name = (mod.get("properties", {}).get("name") or "").strip()
            if uid and name:
                uid_to_name[uid] = name

    # Expand summaries dict: add uid-keyed entries alongside name-keyed entries
    module_summaries: dict[str, Any] = dict(raw_summaries)
    uid_mapped = 0
    for uid, name in uid_to_name.items():
        if name in raw_summaries and uid not in module_summaries:
            module_summaries[uid] = raw_summaries[name]
            uid_mapped += 1

    log.info(
        "compose_bottomup_summary_mapping",
        raw_summary_keys=len(raw_summaries),
        uid_to_name_entries=len(uid_to_name),
        uid_mapped=uid_mapped,
        expanded_keys=len(module_summaries),
    )

    topo = tree.topological_order()
    leaves = [n for n in topo if n.is_leaf()]
    parents = [n for n in topo if not n.is_leaf()]

    reuse_count = 0
    llm_count = 0
    for n in leaves:
        if module_summaries:
            has_match = any(
                module_summaries.get(uid) and (module_summaries[uid].get("summary_text") or module_summaries[uid].get("summary"))
                for uid in n.entity_uids
                if isinstance(module_summaries.get(uid), dict)
            )
            if has_match:
                reuse_count += 1
            else:
                llm_count += 1
        else:
            llm_count += 1

    log.info(
        "compose_bottomup_match_stats",
        total_leaves=len(leaves),
        reuse_from_summaries=reuse_count,
        need_llm=llm_count,
        summary_keys_sample=list(raw_summaries.keys())[:5] if raw_summaries else [],
        leaf_uids_sample=[leaves[0].entity_uids[:3] if leaves else []],
    )

    sem = PipelineConcurrency.semaphore("bottomup")
    progress_counter = [0]
    error_counter = [0]
    timeout_counter = [0]
    import time as _time
    batch_start = _time.monotonic()

    async def _bounded_leaf(node: Any) -> dict[str, Any]:
        async with sem:
            leaf_start = _time.monotonic()
            try:
                result = await asyncio.wait_for(
                    _compose_leaf_for_bottomup(
                        node,
                        llm,
                        module_summaries,
                        graph_store=graph_store,
                        budget_resolver=budget_resolver,
                    ),
                    timeout=_LEAF_TIMEOUT_SEC,
                )
            except TimeoutError:
                timeout_counter[0] += 1
                log.warning(
                    "compose_bottomup_leaf_timeout",
                    key=node.canonical_key,
                    timeout_sec=_LEAF_TIMEOUT_SEC,
                    total_timeouts=timeout_counter[0],
                )
                result = {
                    "path": node.canonical_key,
                    "title": node.title or node.canonical_key,
                    "content": f"# {node.title or node.canonical_key}\n\n(Generation timed out)",
                    "business_domain": node.canonical_key,
                    "canonical_key": node.canonical_key,
                }
            progress_counter[0] += 1
            elapsed = _time.monotonic() - leaf_start
            if progress_counter[0] % 20 == 0 or elapsed > 30:
                total_elapsed = _time.monotonic() - batch_start
                log.info(
                    "compose_bottomup_progress",
                    done=progress_counter[0],
                    total=len(leaves),
                    errors=error_counter[0],
                    timeouts=timeout_counter[0],
                    last_leaf_sec=round(elapsed, 1),
                    total_elapsed_sec=round(total_elapsed, 1),
                    last_key=node.canonical_key,
                )
            return result

    if leaves:
        log.info(
            "compose_bottomup_leaves",
            count=len(leaves),
            has_llm=llm is not None,
            has_graph_store=graph_store is not None,
            concurrency=PipelineConcurrency.limit("bottomup"),
            leaf_timeout_sec=_LEAF_TIMEOUT_SEC,
            sample_keys=[n.canonical_key for n in leaves[:5]],
            sample_uids=[n.entity_uids[:2] for n in leaves[:3]],
        )
        leaf_results = await asyncio.gather(
            *[_bounded_leaf(n) for n in leaves],
            return_exceptions=True,
        )
        for node, result in zip(leaves, leaf_results):
            if isinstance(result, Exception):
                error_counter[0] += 1
                log.warning(
                    "compose_bottomup_leaf_error",
                    key=node.canonical_key,
                    error=str(result),
                    error_type=type(result).__name__,
                    total_errors=error_counter[0],
                )
                result = {
                    "path": node.canonical_key,
                    "title": node.title or node.canonical_key,
                    "content": f"# {node.title or node.canonical_key}\n\n(Generation failed)",
                    "business_domain": node.canonical_key,
                    "canonical_key": node.canonical_key,
                }
            node_contents[node.canonical_key] = result.get("content", "")
            pages.append(result)

        leaves_elapsed = _time.monotonic() - batch_start
        log.info(
            "compose_bottomup_leaves_done",
            total=len(leaves),
            errors=error_counter[0],
            timeouts=timeout_counter[0],
            elapsed_sec=round(leaves_elapsed, 1),
        )

    if parents:
        parent_start = _time.monotonic()
        parent_sem = PipelineConcurrency.semaphore("bottomup")
        parent_by_key = {n.canonical_key: n for n in parents}
        remaining: set[str] = set(parent_by_key.keys())
        parents_done = 0
        wave_num = 0

        log.info(
            "compose_bottomup_parents_start",
            total_parents=len(parents),
            node_contents_keys=len(node_contents),
        )

        async def _bounded_parent(node: Any) -> dict[str, Any]:
            async with parent_sem:
                child_contents = [
                    node_contents.get(c.canonical_key, "")
                    for c in node.children
                ]
                try:
                    page_dict = await asyncio.wait_for(
                        _synthesize_parent_for_bottomup(
                            node, child_contents, llm,
                        ),
                        timeout=_PARENT_TIMEOUT_SEC,
                    )
                except TimeoutError:
                    log.warning(
                        "compose_bottomup_parent_timeout",
                        key=node.canonical_key,
                    )
                    page_dict = {
                        "path": node.canonical_key,
                        "title": node.title or node.canonical_key,
                        "content": (
                            f"# {node.title or node.canonical_key}\n\n"
                            "(Synthesis timed out)"
                        ),
                        "business_domain": node.canonical_key,
                        "canonical_key": node.canonical_key,
                    }
                return page_dict

        while remaining:
            wave_num += 1
            ready = [
                parent_by_key[k]
                for k in remaining
                if all(
                    c.canonical_key in node_contents
                    for c in parent_by_key[k].children
                )
            ]
            if not ready:
                blocked_sample = []
                for k in list(remaining)[:5]:
                    missing = [
                        c.canonical_key
                        for c in parent_by_key[k].children
                        if c.canonical_key not in node_contents
                    ]
                    blocked_sample.append({"parent": k, "missing_children": missing[:3]})
                log.error(
                    "compose_bottomup_parents_deadlock",
                    remaining_count=len(remaining),
                    remaining_sample=sorted(remaining)[:10],
                    blocked_sample=blocked_sample,
                )
                raise RuntimeError(
                    "compose_bottomup: no ready parents while nodes remain; "
                    "tree state is inconsistent",
                )

            log.info(
                "compose_bottomup_parents_wave",
                wave=wave_num,
                ready_count=len(ready),
                remaining_count=len(remaining),
                ready_keys=[n.canonical_key for n in ready[:5]],
            )
            gathered = await asyncio.gather(
                *[_bounded_parent(n) for n in ready],
                return_exceptions=True,
            )

            for node, result in zip(ready, gathered):
                if isinstance(result, Exception):
                    log.warning(
                        "compose_bottomup_parent_error",
                        key=node.canonical_key,
                        error=str(result),
                        error_type=type(result).__name__,
                    )
                    page_dict = {
                        "path": node.canonical_key,
                        "title": node.title or node.canonical_key,
                        "content": (
                            f"# {node.title or node.canonical_key}\n\n"
                            "(Generation failed)"
                        ),
                        "business_domain": node.canonical_key,
                        "canonical_key": node.canonical_key,
                    }
                else:
                    page_dict = result
                node_contents[node.canonical_key] = page_dict.get("content", "")
                pages.append(page_dict)
                remaining.discard(node.canonical_key)
                parents_done += 1
                if parents_done % 20 == 0:
                    log.info(
                        "compose_bottomup_parents_progress",
                        done=parents_done,
                        total=len(parents),
                        elapsed_sec=round(
                            _time.monotonic() - parent_start, 1,
                        ),
                    )

    total_elapsed = _time.monotonic() - batch_start
    log.info(
        "compose_bottomup_done",
        total_pages=len(pages),
        leaves=len(leaves),
        parents=len(parents),
        errors=error_counter[0],
        timeouts=timeout_counter[0],
        total_elapsed_sec=round(total_elapsed, 1),
    )

    return {"pages": pages, "domain_cache": domain_cache}


async def _enrich_leaf_context(node: Any, graph_store: Any) -> str:
    """Batch graph queries to gather rich context for a leaf node. No LLM calls."""
    import time as _time

    from wiki.cypher_queries import CALLERS_CY, CHUNK_SNIPPETS_CY, METHODS_CY, call_chain_cypher

    names = list(node.entity_uids[:15])
    if not names:
        log.debug("enrich_context_skip_empty", key=node.canonical_key)
        return ""

    # UID format: "{label}:{file_path}:{name}:{start_line}" — Cypher uses m.name
    short_names = []
    for uid in names:
        parts = uid.split(":")
        short_names.append(parts[-2] if len(parts) >= 3 else uid)

    log.info(
        "enrich_context_params",
        key=node.canonical_key,
        uid_count=len(names),
        uid_sample=names[:3],
        short_name_sample=short_names[:3],
    )

    params = {"names": short_names, "valid_pairs": []}
    enrich_start = _time.monotonic()

    async def _safe_query(cypher: str, label: str) -> list[dict]:
        q_start = _time.monotonic()
        try:
            result = await asyncio.wait_for(
                graph_store.execute_query(cypher, params),
                timeout=30,
            )
            rows = getattr(result, "data", []) or []
            elapsed = _time.monotonic() - q_start
            if elapsed > 5:
                log.warning(
                    "enrich_context_slow_query",
                    key=node.canonical_key,
                    query_label=label,
                    elapsed_sec=round(elapsed, 1),
                    rows=len(rows),
                )
            return rows
        except TimeoutError:
            log.warning(
                "enrich_context_query_timeout",
                key=node.canonical_key,
                query_label=label,
            )
            return []
        except Exception:
            log.warning("enrich_context_query_failed", query_label=label, exc_info=True)
            return []

    methods_rows, callers_rows, chain_rows, snippet_rows = await asyncio.gather(
        _safe_query(METHODS_CY, "methods"),
        _safe_query(CALLERS_CY, "callers"),
        _safe_query(call_chain_cypher(2), "call_chain"),
        _safe_query(CHUNK_SNIPPETS_CY, "snippets"),
    )
    enrich_elapsed = _time.monotonic() - enrich_start
    total_rows = len(methods_rows) + len(callers_rows) + len(chain_rows) + len(snippet_rows)
    log.info(
        "enrich_context_result",
        key=node.canonical_key,
        elapsed_sec=round(enrich_elapsed, 1),
        methods=len(methods_rows),
        callers=len(callers_rows),
        chains=len(chain_rows),
        snippets=len(snippet_rows),
        total_rows=total_rows,
        context_empty=total_rows == 0,
    )

    sections: list[str] = []

    if methods_rows:
        lines = ["### 方法签名"]
        for r in methods_rows[:20]:
            sig = r.get("signature", "")
            doc = r.get("docstring", "")
            lines.append(
                f"- `{r.get('module_name', '')}.{r.get('func_name', '')}({sig})`"
                + (f" — {doc[:80]}" if doc else "")
            )
        sections.append("\n".join(lines))

    if callers_rows:
        lines = ["### 调用方"]
        for r in callers_rows[:15]:
            lines.append(f"- {r.get('caller_name', '')} → {r.get('target_name', '')}")
        sections.append("\n".join(lines))

    if chain_rows:
        lines = ["### 调用链"]
        for r in chain_rows[:10]:
            c_fns = r.get("caller_functions", [])
            e_fns = r.get("callee_functions", [])
            fn_info = f" [{','.join(c_fns[:3])} → {','.join(e_fns[:3])}]" if c_fns or e_fns else ""
            lines.append(f"- {r.get('caller', '')} → {r.get('callee', '')}{fn_info}")
        sections.append("\n".join(lines))

    if snippet_rows:
        lines = ["### 关键代码"]
        for r in snippet_rows[:5]:
            snippet = r.get("snippet", "")[:1500]
            lines.append(f"**{r.get('entity_name', '')}** ({r.get('file_path', '')})")
            lines.append(f"```\n{snippet}\n```")
        sections.append("\n".join(lines))

    context = "\n\n".join(sections)
    return context[:8000]


async def _compose_leaf_for_bottomup(
    node: Any,
    llm: Any,
    module_summaries: dict[str, Any] | None = None,
    *,
    graph_store: Any | None = None,
    budget_resolver: Any | None = None,
) -> dict[str, Any]:
    import time as _time
    leaf_start = _time.monotonic()
    title = node.title or node.canonical_key
    source = "unknown"

    collected_summaries: list[dict[str, Any]] = []
    if module_summaries:
        for uid in node.entity_uids:
            s = module_summaries.get(uid)
            if s and isinstance(s, dict) and (s.get("summary_text") or s.get("summary")):
                collected_summaries.append(s)

    enriched_context = ""
    if graph_store and not collected_summaries:
        try:
            enriched_context = await _enrich_leaf_context(node, graph_store)
        except Exception:
            log.warning("enrich_context_failed", key=node.canonical_key, exc_info=True)

    if collected_summaries:
        source = "reuse"
        sections: list[str] = []
        for s in collected_summaries:
            section = s.get("summary_text") or s.get("summary", "")
            methods = s.get("key_methods", [])
            if methods:
                section += "\n\n**Key Methods:** " + ", ".join(f"`{m}`" for m in methods[:5])
            deps = s.get("dependencies", [])
            if deps:
                section += "\n\n**Dependencies:** " + ", ".join(f"`{d}`" for d in deps[:5])
            sections.append(section)
        content = f"# {title}\n\n" + "\n\n---\n\n".join(sections)
        log.debug("compose_leaf_reused", key=node.canonical_key, sections=len(sections))
    elif not llm:
        source = "no_llm"
        content = f"# {title}\n\n(No LLM available)"
    else:
        source = "llm"
        system = "你是代码文档专家，根据代码模块信息生成清晰的 Wiki 文档页面。输出 Markdown 格式。"
        context_section = f"\n\n## 代码上下文\n\n{enriched_context}" if enriched_context else ""
        prompt = (
            f"为代码模块「{title}」生成 Wiki 文档。\n"
            f"包含的代码实体: {', '.join(node.entity_uids[:15])}\n"
            f"文件路径: {', '.join(node.file_paths[:10])}\n"
            f"{context_section}"
        )
        llm_start = _time.monotonic()
        try:
            from wiki.token_budget import resolve_max_tokens

            compose_tokens = resolve_max_tokens(budget_resolver, "leaf_compose")
            content = await llm.generate(prompt, system=system, max_tokens=compose_tokens)
            llm_elapsed = _time.monotonic() - llm_start
            if llm_elapsed > 15:
                log.warning(
                    "compose_leaf_llm_slow",
                    key=node.canonical_key,
                    llm_sec=round(llm_elapsed, 1),
                )
        except Exception:
            log.warning("compose_leaf_failed", canonical_key=node.canonical_key, exc_info=True)
            content = f"# {title}\n\n(Generation failed)"

    total_elapsed = _time.monotonic() - leaf_start
    if total_elapsed > 20:
        log.warning(
            "compose_leaf_slow",
            key=node.canonical_key,
            source=source,
            elapsed_sec=round(total_elapsed, 1),
            has_context=bool(enriched_context),
        )

    return {
        "path": node.canonical_key,
        "title": title,
        "content": content if isinstance(content, str) else str(content),
        "business_domain": node.canonical_key,
        "canonical_key": node.canonical_key,
    }


async def _synthesize_parent_for_bottomup(
    node: Any,
    child_contents: list[str],
    llm: Any,
) -> dict[str, Any]:
    from wiki.parent_synthesizer import ParentSynthesizer

    title = node.title or node.canonical_key
    if not llm:
        titles = "\n".join(f"- {c.title or c.canonical_key}" for c in node.children)
        return {
            "path": node.canonical_key,
            "title": title,
            "content": f"# {title}\n\n## Sub-modules\n{titles}",
            "business_domain": node.canonical_key,
            "canonical_key": node.canonical_key,
        }

    synth = ParentSynthesizer(llm=llm)
    content = await synth.synthesize(node, child_contents)
    if not isinstance(content, str):
        content = str(content)
    return {
        "path": node.canonical_key,
        "title": title,
        "content": content,
        "business_domain": node.canonical_key,
        "canonical_key": node.canonical_key,
    }
