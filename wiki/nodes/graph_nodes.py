"""Pipeline nodes for graph-based wiki decomposition and bottom-up composition."""

import asyncio
import json
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger

log = get_logger(__name__)

_BOTTOMUP_CONCURRENCY = 12


async def graph_decompose_node(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Build module tree from dependency graph using SCC + topological sort."""
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
            name = (props.get("name") or mod.get("uid") or "").strip()
            if not name:
                continue
            nodes.append(name)
            fp = props.get("file_path", "")
            node_files[name] = [fp] if fp else []
            node_tokens[name] = int(props.get("code_length", 0) or 0) // 4

    edges: list[tuple[str, str]] = []
    if graph_store:
        node_set = set(nodes)
        for repo in state.get("repositories", []):
            try:
                result = await graph_store.execute_query(
                    "MATCH (a)-[r:DEPENDS_ON|CALLS|IMPORTS]->(b) "
                    "WHERE a.repo_id = $repo_id AND b.repo_id = $repo_id "
                    "RETURN a.name AS a_uid, b.name AS b_uid",
                    {"repo_id": repo},
                )
                for row in getattr(result, "data", []) or []:
                    a = row.get("a_uid", "")
                    b = row.get("b_uid", "")
                    if a and b and a in node_set and b in node_set:
                        edges.append((a, b))
            except Exception:
                log.warning("graph_decompose_query_failed", repo=repo, exc_info=True)

    llm = configurable.get("llm")
    decomposer = GraphModuleDecomposer(llm=llm)
    repo_id = state.get("business_id", "")

    log.info(
        "graph_decompose_input",
        node_count=len(nodes),
        edge_count=len(edges),
        has_llm=llm is not None,
    )

    tree = decomposer.decompose_from_graph(
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

    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    canonical_keys = dict(state.get("canonical_keys", {}))

    nodes_needing_llm: list[Any] = []
    for node in tree.all_nodes():
        if node.title:
            canonical_keys[node.canonical_key] = node.title
            continue
        if len(node.entity_uids) == 1:
            node.title = node.entity_uids[0]
            canonical_keys[node.canonical_key] = node.title
        elif node.file_paths:
            node.title = node.file_paths[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            canonical_keys[node.canonical_key] = node.title
        elif llm:
            nodes_needing_llm.append(node)
        else:
            node.title = node.canonical_key
            canonical_keys[node.canonical_key] = node.title

    if nodes_needing_llm and llm:
        log.info("generate_titles_llm", count=len(nodes_needing_llm))
        sem = asyncio.Semaphore(_BOTTOMUP_CONCURRENCY)

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
                    raw_text = await llm.generate(prompt, max_tokens=200)
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
    from wiki.models.module_tree import ModuleTree

    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")
    repo_path = configurable.get("repo_path")
    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    domain_cache = dict(state.get("domain_cache", {}))

    log.info(
        "compose_bottomup_start",
        tree_roots=len(tree.roots),
        tree_nodes=len(tree.all_nodes()),
        has_llm=llm is not None,
        has_graph_store=graph_store is not None,
        existing_pages=len(state.get("pages", [])),
        config_is_none=config is None,
        configurable_keys=list(configurable.keys()) if configurable else [],
    )

    module_summaries = state.get("module_summaries", {})
    pages: list[dict[str, Any]] = list(state.get("pages", []))
    node_contents: dict[str, str] = {}

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
        summary_keys_sample=list(module_summaries.keys())[:5] if module_summaries else [],
        leaf_uids_sample=[leaves[0].entity_uids[:3] if leaves else []],
    )

    sem = asyncio.Semaphore(_BOTTOMUP_CONCURRENCY)
    progress_counter = [0]

    async def _bounded_leaf(node: Any) -> dict[str, Any]:
        async with sem:
            result = await _compose_leaf_for_bottomup(
                node,
                llm,
                module_summaries,
                graph_store=graph_store,
                repo_path=repo_path,
            )
            progress_counter[0] += 1
            if progress_counter[0] % 100 == 0:
                log.info("compose_bottomup_progress", done=progress_counter[0], total=len(leaves))
            return result

    if leaves:
        log.info("compose_bottomup_leaves", count=len(leaves), has_llm=llm is not None)
        leaf_results = await asyncio.gather(
            *[_bounded_leaf(n) for n in leaves],
            return_exceptions=True,
        )
        for node, result in zip(leaves, leaf_results):
            if isinstance(result, Exception):
                log.warning("compose_bottomup_leaf_error", key=node.canonical_key, error=str(result))
                result = {
                    "path": node.canonical_key,
                    "title": node.title or node.canonical_key,
                    "content": f"# {node.title or node.canonical_key}\n\n(Generation failed)",
                    "business_domain": node.canonical_key,
                    "canonical_key": node.canonical_key,
                }
            node_contents[node.canonical_key] = result.get("content", "")
            pages.append(result)

    for node in parents:
        child_contents = [
            node_contents.get(c.canonical_key, "")
            for c in node.children
        ]
        page_dict = await _synthesize_parent_for_bottomup(node, child_contents, llm)
        node_contents[node.canonical_key] = page_dict.get("content", "")
        pages.append(page_dict)

    return {"pages": pages, "domain_cache": domain_cache}


async def _compose_leaf_for_bottomup(
    node: Any,
    llm: Any,
    module_summaries: dict[str, Any] | None = None,
    *,
    graph_store: Any | None = None,
    repo_path: str | None = None,
) -> dict[str, Any]:
    title = node.title or node.canonical_key

    collected_summaries: list[dict[str, Any]] = []
    if module_summaries:
        for uid in node.entity_uids:
            s = module_summaries.get(uid)
            if s and isinstance(s, dict) and (s.get("summary_text") or s.get("summary")):
                collected_summaries.append(s)

    baseline_context = ""
    if collected_summaries:
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
        baseline_context = "\n\n---\n\n".join(sections)

    if llm and graph_store:
        from wiki.page_agent import WikiPageAgent

        try:
            agent = WikiPageAgent(
                llm=llm,
                graph_store=graph_store,
                repo_path=repo_path,
            )
            result_content = await agent.generate(
                module_names=list(node.entity_uids[:15]),
                domain_name=node.canonical_key,
                baseline_context=baseline_context,
                max_rounds=6,
            )
            if result_content and len(str(result_content).strip()) > 50:
                return {
                    "path": node.canonical_key,
                    "title": title,
                    "content": result_content if isinstance(result_content, str) else str(result_content),
                    "business_domain": node.canonical_key,
                    "canonical_key": node.canonical_key,
                }
        except Exception:
            log.warning("compose_leaf_agent_failed", canonical_key=node.canonical_key, exc_info=True)

    if baseline_context:
        content = f"# {title}\n\n{baseline_context}"
        log.debug("compose_leaf_reused", key=node.canonical_key, sections=len(collected_summaries))
    elif not llm:
        content = f"# {title}\n\n(No LLM available)"
    else:
        system = "你是代码文档专家，根据代码模块信息生成清晰的 Wiki 文档页面。输出 Markdown 格式。"
        prompt = (
            f"为代码模块「{title}」生成 Wiki 文档。\n"
            f"包含的代码实体: {', '.join(node.entity_uids[:15])}\n"
            f"文件路径: {', '.join(node.file_paths[:10])}\n"
        )
        try:
            content = await llm.generate(prompt, system=system, max_tokens=2000)
        except Exception:
            log.warning("compose_leaf_failed", canonical_key=node.canonical_key, exc_info=True)
            content = f"# {title}\n\n(Generation failed)"

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
