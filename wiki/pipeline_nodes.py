"""LangGraph pipeline node implementations for Wiki generation.

Implementations live in ``wiki.nodes``; this module re-exports the public API
and patch targets (``log``, ``HierarchicalDecomposer``, ``TopicPageComposer``,
``TokenBudgetResolver``) for backward compatibility.
"""

from core.log import get_logger
from wiki.dependency_graph import HierarchicalDecomposer
from wiki.token_budget import TokenBudgetResolver
from wiki.topic_page_composer import TopicPageComposer
from wiki.topo_sort import topological_order  # noqa: F401

log = get_logger(__name__)

from wiki.nodes.aggregate import (
    compose_parent_pages_node,
    summarize_leaves_node,
    synthesize_overviews_node,
)
from wiki.nodes.classify import (
    classify_domains_node,
    classify_entities_node,
    decompose_hierarchy_node,
    detect_reorg_node,
    set_review_status_node,
)
from wiki.nodes.classify_architecture import classify_architecture_layers_node
from wiki.nodes.compose import (
    _compose_from_topic_structure,
    _compose_single_leaf_domain,
    _topic_to_domain_dict,
    compose_leaf_modules_node,
    compose_leaf_pages_node,
    plan_topic_structure_node,
)
from wiki.nodes.domain_compose import compose_domain_agents_node
from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node
from wiki.nodes.graph_nodes import (
    assign_canonical_keys_node,
    compose_bottomup_node,
    generate_titles_node,
    graph_decompose_node,
)
from wiki.nodes.heal import heal_pages_node
from wiki.nodes.links import create_links_node
from wiki.nodes.persist_classification import persist_classification_node
from wiki.nodes.reassemble_domains import reassemble_domains_node
from wiki.nodes.tour import generate_tour_node  # noqa: F401
from wiki.nodes.utils import (
    _COMPOSE_CONCURRENCY,
    _MAX_LEAF_MODULES,
    _build_page_data_for_semantic_diagrams,
    _build_subdomain_interactions,
    _call_target_module,
    _collect_leaf_domains,
    _collect_module_names_in_subtree,
    _collect_parent_domains_by_level,
    _count_modules_in_domain_tree,
    _detect_oversized_leaves,
    _extract_key_entities,
    _extract_summary_from_content,
    _find_domain_in_tree,
    _find_page_for_leaf_domain,
    _flatten_all_domains,
    _module_dicts_for_names,
    _normalize_domain_tree,
    _normalize_pages_map,
    has_parent_domains,
    select_key_snippets,
)

__all__ = [
    "HierarchicalDecomposer",
    "TokenBudgetResolver",
    "TopicPageComposer",
    "_COMPOSE_CONCURRENCY",
    "_MAX_LEAF_MODULES",
    "_build_page_data_for_semantic_diagrams",
    "_build_subdomain_interactions",
    "_call_target_module",
    "_collect_leaf_domains",
    "_collect_module_names_in_subtree",
    "_collect_parent_domains_by_level",
    "_compose_from_topic_structure",
    "_compose_single_leaf_domain",
    "_count_modules_in_domain_tree",
    "_detect_oversized_leaves",
    "_extract_key_entities",
    "_extract_summary_from_content",
    "_find_domain_in_tree",
    "_find_page_for_leaf_domain",
    "_flatten_all_domains",
    "_module_dicts_for_names",
    "_normalize_domain_tree",
    "_normalize_pages_map",
    "_topic_to_domain_dict",
    "assign_canonical_keys_node",
    "classify_architecture_layers_node",
    "classify_domains_node",
    "classify_entities_node",
    "compose_bottomup_node",
    "compose_domain_agents_node",
    "compose_leaf_modules_node",
    "compose_leaf_pages_node",
    "compose_parent_pages_node",
    "create_links_node",
    "decompose_hierarchy_node",
    "detect_reorg_node",
    "generate_titles_node",
    "generate_tour_node",
    "graph_decompose_node",
    "graph_driven_domain_decompose_node",
    "has_parent_domains",
    "heal_pages_node",
    "log",
    "persist_classification_node",
    "plan_topic_structure_node",
    "reassemble_domains_node",
    "select_key_snippets",
    "set_review_status_node",
    "summarize_leaves_node",
    "synthesize_overviews_node",
]
