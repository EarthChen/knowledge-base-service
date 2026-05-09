"""Pipeline nodes for graph-based wiki decomposition and bottom-up composition."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger

log = get_logger(__name__)


def _llm_text_response(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    gens = getattr(raw, "generations", None)
    if gens and gens[0]:
        g0 = gens[0][0] if isinstance(gens[0], (list, tuple)) else gens[0]
        msg = getattr(g0, "message", None) if g0 is not None else None
        if msg is not None and getattr(msg, "content", None):
            c = msg.content
            return c if isinstance(c, str) else str(c)
        txt = getattr(g0, "text", None)
        if txt is not None:
            return txt if isinstance(txt, str) else str(txt)
    return str(raw) if raw is not None else ""


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
    tree = decomposer.decompose_from_graph(
        nodes, edges, node_files, node_tokens, repo_id,
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

    for node in tree.all_nodes():
        if node.title:
            canonical_keys[node.canonical_key] = node.title
            continue
        if llm:
            try:
                entity_names = ", ".join(node.entity_uids[:10])
                file_names = ", ".join(node.file_paths[:5])
                prompt = (
                    f"为以下代码模块生成一个简洁的中文标题和一句话描述。\n"
                    f"模块key: {node.canonical_key}\n"
                    f"代码实体: {entity_names}\n"
                    f"文件路径: {file_names}\n"
                    f'输出JSON: {{"title": "标题", "description": "描述"}}'
                )
                raw = await llm.agenerate([[{"role": "user", "content": prompt}]])
                raw_text = _llm_text_response(raw)
                data = json.loads(raw_text) if raw_text else {}
                node.title = data.get("title", node.canonical_key)
                node.description = data.get("description", "")
            except Exception:
                log.warning(
                    "generate_titles_failed",
                    canonical_key=node.canonical_key,
                    exc_info=True,
                )
                node.title = node.canonical_key
        else:
            node.title = node.canonical_key
        canonical_keys[node.canonical_key] = node.title

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
    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    domain_cache = dict(state.get("domain_cache", {}))

    pages: list[dict[str, Any]] = list(state.get("pages", []))
    node_contents: dict[str, str] = {}

    for node in tree.topological_order():
        if node.is_leaf():
            page_dict = await _compose_leaf_for_bottomup(node, llm)
        else:
            child_contents = [
                node_contents.get(c.canonical_key, "")
                for c in node.children
            ]
            page_dict = await _synthesize_parent_for_bottomup(node, child_contents, llm)
        node_contents[node.canonical_key] = page_dict.get("content", "")
        pages.append(page_dict)

    return {"pages": pages, "domain_cache": domain_cache}


async def _compose_leaf_for_bottomup(node: Any, llm: Any) -> dict[str, Any]:
    title = node.title or node.canonical_key
    if not llm:
        return {
            "path": node.canonical_key,
            "title": title,
            "content": f"# {title}\n\n(No LLM available)",
            "business_domain": node.canonical_key,
            "canonical_key": node.canonical_key,
        }

    prompt = (
        f"为代码模块「{title}」生成 Wiki 文档。\n"
        f"包含的代码实体: {', '.join(node.entity_uids[:15])}\n"
        f"文件路径: {', '.join(node.file_paths[:10])}\n"
    )
    try:
        raw = await llm.agenerate([[{"role": "user", "content": prompt}]])
        content = _llm_text_response(raw)
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
        content = _llm_text_response(content)
    return {
        "path": node.canonical_key,
        "title": title,
        "content": content,
        "business_domain": node.canonical_key,
        "canonical_key": node.canonical_key,
    }
