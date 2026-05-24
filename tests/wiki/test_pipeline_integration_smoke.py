"""Smoke test: verify all new components are importable and wired into the pipeline."""


def test_all_components_importable():
    """All pipeline integration components must be importable."""
    from wiki.context_gap import cleanup_context_gaps, CONTEXT_GAP_RE
    from wiki.citation_verifier import verify_citations, extract_code_references
    from wiki.topo_sort import topological_order
    from wiki.overview_synthesizer import synthesize_overview_from_children
    from wiki.agent_config import AgentConfig
    from wiki.page_agent import WikiPageAgent
    from wiki.domain_merger import merge_small_domains
    from indexer.post_process import supplement_contains_relationships

    _ = (
        cleanup_context_gaps,
        CONTEXT_GAP_RE,
        verify_citations,
        extract_code_references,
        topological_order,
        synthesize_overview_from_children,
        AgentConfig,
        WikiPageAgent,
        merge_small_domains,
        supplement_contains_relationships,
    )


def test_agent_config_defaults():
    from wiki.agent_config import AgentConfig

    cfg = AgentConfig.from_env()
    assert cfg.enabled is False, "Agent-Driven should be disabled by default"
    assert cfg.simple_threshold == 1


def test_compose_has_agent_path():
    """compose.py must reference AgentConfig for routing."""
    with open("wiki/nodes/compose.py") as f:
        source = f.read()
    assert "AgentConfig" in source
    assert "should_use_agent" in source


def test_quality_gate_has_citation_check():
    """quality_gate_node must reference citation_verifier."""
    with open("wiki/nodes/quality_gate.py") as f:
        source = f.read()
    assert "citation_verifier" in source or "verify_citations" in source


def test_tree_linker_has_overview_synthesizer():
    """tree_linker must use overview_synthesizer."""
    with open("wiki/tree_linker.py") as f:
        source = f.read()
    assert "overview_synthesizer" in source or "synthesize_overview_from_children" in source


def test_indexer_has_contains_supplement():
    """indexer must call supplement_contains_relationships."""
    with open("indexer/incremental_indexer.py") as f:
        source = f.read()
    assert "supplement_contains_relationships" in source


def test_pipeline_nodes_has_topo_sort():
    """pipeline_nodes or compose must use topological_order."""
    found = False
    for path in ("wiki/pipeline_nodes.py", "wiki/nodes/compose.py"):
        with open(path) as f:
            if "topological_order" in f.read() or "topo_sort" in f.read():
                found = True
                break
    # re-read to check both patterns in the same file
    for path in ("wiki/pipeline_nodes.py", "wiki/nodes/compose.py"):
        with open(path) as f:
            content = f.read()
            if "topological_order" in content or "topo_sort" in content:
                found = True
                break
    assert found, "pipeline must use topological_order for domain ordering"


def test_dependency_graph_has_small_domain_merge():
    """dependency_graph must use merge_small_domains."""
    with open("wiki/dependency_graph.py") as f:
        source = f.read()
    assert "merge_small_domains" in source
