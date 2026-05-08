"""Smoke test: verify all remaining optimizations are wired correctly at source level."""
import inspect

import pytest


def test_r1_ccb_no_method_map_bug():
    """CCB _query_call_chains should not contain the old method_map iteration pattern."""
    from wiki.content_context_builder import ContentContextBuilder
    source = inspect.getsource(ContentContextBuilder._query_call_chains)
    assert "method_map.items()" not in source
    assert "caller_functions" in source


def test_r2c_decompose_uses_real_edges():
    """decompose_hierarchy_node should import ModuleDependencyGraph."""
    from wiki.nodes import classify
    source = inspect.getsource(classify.decompose_hierarchy_node)
    assert "ModuleDependencyGraph" in source


def test_r2a_graph_pre_grouper_exists():
    """graph_pre_grouper module should be importable with expected API."""
    from wiki.graph_pre_grouper import compute_pre_groups, PreGroup
    assert callable(compute_pre_groups)
    # Dataclass fields are not class attributes; use __dataclass_fields__.
    fields = PreGroup.__dataclass_fields__
    assert "module_names" in fields
    assert "directory_prefix" in fields


def test_r2b_planner_accepts_pre_groups():
    """_build_single_batch_prompt should accept pre_groups parameter."""
    from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
    sig = inspect.signature(CrossRepoBusinessDomainPlanner._build_single_batch_prompt)
    assert "pre_groups" in sig.parameters


def test_r3_merge_small_leaves_exists():
    """_merge_small_leaves should be importable from compose module."""
    from wiki.nodes.compose import _merge_small_leaves
    assert callable(_merge_small_leaves)


def test_r3_compose_calls_merge_small_leaves():
    """compose_leaf_pages_node should call _merge_small_leaves."""
    from wiki.nodes import compose
    source = inspect.getsource(compose.compose_leaf_pages_node)
    assert "_merge_small_leaves" in source


def test_r5_ccb_before_agent_in_compose():
    """CCB context should be built before Agent check in _compose_single_leaf_domain."""
    from wiki.nodes import compose
    source = inspect.getsource(compose._compose_single_leaf_domain)
    ccb_pos = source.find("ContentContextBuilder")
    agent_pos = source.find("AgentConfig")
    assert ccb_pos < agent_pos, "CCB should run before AgentConfig check"


def test_r5_agent_uses_format_summary():
    """Agent path should reference format_summary_for_agent."""
    from wiki.nodes import compose
    source = inspect.getsource(compose._compose_single_leaf_domain)
    assert "format_summary_for_agent" in source
