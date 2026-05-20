from wiki.pipeline_graph import build_wiki_pipeline


def test_pipeline_has_new_nodes():
    pipeline = build_wiki_pipeline(checkpointer=False)
    node_names = set(pipeline.nodes.keys())
    assert "graph_decompose" in node_names
    assert "assign_canonical_keys" in node_names
    assert "generate_titles" in node_names
    assert "compose_domain_agents" in node_names
    assert "summarize_leaves" in node_names
    assert "compose_parent_pages" in node_names


def test_pipeline_removed_old_nodes():
    pipeline = build_wiki_pipeline(checkpointer=False)
    node_names = set(pipeline.nodes.keys())
    assert "classify_domains" in node_names
    assert "decompose_hierarchy" not in node_names
    assert "plan_topic_structure" not in node_names
    assert "compose_leaf_pages" not in node_names
    assert "synthesize_overviews" not in node_names
