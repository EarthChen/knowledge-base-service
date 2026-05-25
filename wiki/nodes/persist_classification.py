from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.tree_builder import WikiTreeBuilder

log = get_logger(__name__)


async def persist_classification_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Persist domain classification and tree structure immediately after decomposition.

    Runs right after graph_domain_decompose so the domain tree is visible
    in the UI without waiting for the full pipeline to finish.

    Persists:
    1. WikiSpace + WikiSection hierarchy (domain tree visible in UI)
    2. Pipeline domain tree snapshot (for incremental diffing)
    3. business_domain property on Module graph nodes
    """
    business_id = state.get("business_id", "")
    domain_mapping: dict[str, list] = state.get("domain_mapping", {})
    domain_display_names: dict[str, str] = state.get("domain_display_names", {})
    domain_tree: list[dict[str, Any]] | None = state.get("domain_tree")

    if not domain_mapping:
        log.info("persist_classification_skip_empty", business_id=business_id)
        return {"classification_persisted": False}

    configurable = (config or {}).get("configurable", {}) or {}
    wiki_store = configurable.get("wiki_store")
    graph_store = configurable.get("graph_store")

    persisted_tree = False
    persisted_domains = False

    # --- Phase 1: Persist WikiSpace + WikiSection tree ---
    if wiki_store is not None:
        try:
            await _persist_domain_tree_to_wiki(
                wiki_store, business_id, domain_mapping,
                domain_display_names, domain_tree,
            )
            persisted_tree = True
        except Exception:
            log.warning("persist_classification_tree_failed", business_id=business_id, exc_info=True)
    else:
        log.info("persist_classification_no_wiki_store", business_id=business_id)

    # --- Phase 2: Set business_domain on Module nodes ---
    if graph_store is not None:
        try:
            await _persist_domain_labels_on_modules(
                graph_store, business_id, domain_mapping, state.get("modules", {}),
            )
            persisted_domains = True
        except Exception:
            log.warning("persist_classification_module_labels_failed", business_id=business_id, exc_info=True)

    # --- Phase 3: Persist architecture layers on Module nodes ---
    arch_layers = state.get("architecture_layers") or {}
    all_modules = state.get("modules", {})
    if graph_store is not None and arch_layers:
        try:
            await _persist_architecture_layers_on_modules(
                graph_store, all_modules, arch_layers,
            )
        except Exception:
            log.warning("persist_classification_arch_layers_failed", business_id=business_id, exc_info=True)

    log.info(
        "persist_classification_done",
        business_id=business_id,
        domains=len(domain_mapping),
        total_modules=sum(len(v) for v in domain_mapping.values()),
        persisted_tree=persisted_tree,
        persisted_domains=persisted_domains,
    )
    return {"classification_persisted": persisted_tree or persisted_domains}


async def _persist_domain_tree_to_wiki(
    wiki_store: Any,
    business_id: str,
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
    domain_tree: list[dict[str, Any]] | None,
) -> None:
    """Create WikiSpace + WikiSection hierarchy so domain tree is immediately visible."""
    tb = WikiTreeBuilder()
    space_uid = tb.generate_space_uid(business_id)

    await wiki_store.upsert_wiki_space(
        business_id=business_id,
        title=f"{business_id} Knowledge Base",
        description=f"Business-level wiki for {business_id}",
    )

    # Clean up stale WikiSection nodes from previous runs
    try:
        deleted = await wiki_store.delete_domain_sections(space_uid, "business_domain")
        if deleted:
            log.info("persist_classification_cleanup", deleted_sections=deleted)
    except Exception:
        log.warning("persist_classification_cleanup_failed", exc_info=True)

    has_nested = domain_tree is not None and len(domain_tree) > 0

    if has_nested:
        try:
            await wiki_store.persist_pipeline_domain_tree(
                business_id, domain_tree, None,
            )
        except Exception:
            log.warning("persist_classification_tree_snapshot_failed", exc_info=True)

        root_uid = tb.generate_domain_section_uid(business_id, "__root__")
        await wiki_store.upsert_wiki_section(
            uid=root_uid,
            title="__root__",
            description="Nested domain tree root",
            section_type="business_domain",
            sort_order=-1,
            auto_generated=True,
        )
        await wiki_store.add_has_child_edge(
            parent_uid=space_uid,
            parent_label="WikiSpace",
            child_uid=root_uid,
            child_label="WikiSection",
            view_type="business_domain",
            sort_order=0,
        )
        await _create_nested_sections(wiki_store, tb, business_id, root_uid, domain_tree)
    else:
        sort_idx = 1
        for domain_name in domain_mapping:
            section_uid = tb.generate_domain_section_uid(business_id, domain_name)
            section_title = domain_display_names.get(domain_name, domain_name)
            await wiki_store.upsert_wiki_section(
                uid=section_uid,
                title=section_title,
                description=f"Business domain: {section_title}",
                section_type="business_domain",
                sort_order=sort_idx,
                auto_generated=True,
            )
            await wiki_store.add_has_child_edge(
                parent_uid=space_uid,
                parent_label="WikiSpace",
                child_uid=section_uid,
                child_label="WikiSection",
                view_type="business_domain",
                sort_order=sort_idx,
            )
            sort_idx += 1

    log.info(
        "persist_classification_tree_done",
        business_id=business_id,
        nested=has_nested,
        domains=len(domain_mapping),
    )


async def _create_nested_sections(
    wiki_store: Any,
    tb: WikiTreeBuilder,
    business_id: str,
    parent_uid: str,
    nodes: list[dict[str, Any]],
    path_prefix: str = "",
) -> None:
    """Recursively create WikiSection nodes for nested domain tree."""
    for idx, node in enumerate(nodes):
        name = node.get("name", "")
        if not name:
            continue
        domain_path = f"{path_prefix}/{name}" if path_prefix else name
        section_uid = tb.generate_domain_section_uid(business_id, domain_path)
        display_name = node.get("display_name", name)

        try:
            await wiki_store.upsert_wiki_section(
                uid=section_uid,
                title=display_name,
                description=node.get("description", ""),
                section_type="business_domain",
                sort_order=idx,
                auto_generated=True,
            )
            await wiki_store.add_has_child_edge(
                parent_uid=parent_uid,
                parent_label="WikiSection",
                child_uid=section_uid,
                child_label="WikiSection",
                view_type="business_domain",
                sort_order=idx,
            )
        except Exception:
            log.warning("persist_classification_section_failed", domain=name, exc_info=True)
            continue

        children = node.get("children", [])
        if children:
            await _create_nested_sections(
                wiki_store, tb, business_id, section_uid, children, domain_path,
            )


async def _persist_domain_labels_on_modules(
    graph_store: Any,
    business_id: str,
    domain_mapping: dict[str, list],
    all_modules: dict[str, list],
) -> None:
    """Set business_domain property on Module nodes in the graph."""
    updated = 0
    for domain_name, repo_module_pairs in domain_mapping.items():
        for repo, mod_name in repo_module_pairs:
            repo_modules = all_modules.get(repo, [])
            mod_nodes = [
                m for m in repo_modules
                if m.get("properties", {}).get("name") == mod_name
                and m.get("properties", {}).get("repository", repo) == repo
            ]
            if not mod_nodes:
                continue
            mod_node = mod_nodes[0]
            try:
                await graph_store.update_node_property(
                    mod_node.get("label", "Module"),
                    mod_node.get("uid", ""),
                    "business_domain",
                    domain_name,
                )
                updated += 1
            except Exception:
                log.debug(
                    "persist_classification_module_label_failed",
                    module=mod_name, domain=domain_name, exc_info=True,
                )
    log.info("persist_classification_module_labels_done", updated=updated)


async def _persist_architecture_layers_on_modules(
    graph_store: Any,
    all_modules: dict[str, list],
    arch_layers: dict[str, dict[str, Any]],
) -> None:
    """Write wiki_architecture_layer and wiki_architecture_confidence to Module nodes."""
    updated = 0
    for repo, mod_list in all_modules.items():
        if not isinstance(mod_list, list):
            continue
        for mod_dict in mod_list:
            if not isinstance(mod_dict, dict):
                continue
            props = mod_dict.get("properties") or {}
            name = props.get("name", "")
            uid = mod_dict.get("uid", "")
            if not name or not uid:
                continue
            layer_info = arch_layers.get(name)
            if not layer_info:
                continue
            try:
                await graph_store.update_node_property(
                    "Module", uid, "wiki_architecture_layer", layer_info.get("layer", ""),
                )
                await graph_store.update_node_property(
                    "Module", uid, "wiki_architecture_confidence", layer_info.get("confidence", 0.0),
                )
                updated += 1
            except Exception:
                log.debug("persist_arch_layer_failed", module=name, exc_info=True)
    log.info("persist_architecture_layers_done", updated=updated)
