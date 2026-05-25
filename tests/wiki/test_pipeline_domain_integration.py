"""Integration tests: domain classification nodes wired into pipeline."""
from wiki.pipeline_graph import build_wiki_pipeline


class TestDomainClassificationInPipeline:
    def test_pipeline_contains_graph_domain_decompose_node(self):
        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "graph_domain_decompose" in node_names
        assert "classify_domains" not in node_names

    def test_pipeline_no_longer_has_decompose_hierarchy_node(self):
        """decompose_hierarchy merged into graph_domain_decompose."""
        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "decompose_hierarchy" not in node_names


class TestAgentComposeIsDefault:
    def test_default_uses_compose_domain_agents(self):
        """Pipeline always uses compose_domain_agents (agent compose is the only path)."""
        pipeline = build_wiki_pipeline(checkpointer=False)
        nodes = set(pipeline.get_graph().nodes.keys())
        assert "compose_domain_agents" in nodes
        assert "compose_bottomup" not in nodes


class TestAgentPipelineIntegration:
    def test_full_pipeline_with_agent_compose(self):
        """End-to-end: pipeline produces domain pages via agent compose."""
        pipeline = build_wiki_pipeline(checkpointer=False)
        nodes = set(pipeline.get_graph().nodes.keys())
        expected_nodes = {
            "classify_entity_roles",
            "detect_reorg",
            "graph_decompose",
            "assign_canonical_keys",
            "graph_domain_decompose",
            "persist_classification",
            "generate_titles",
            "set_review_status",
            "compose_leaf_modules",
            "compose_domain_agents",
            "quality_gate",
            "heal_pages",
            "create_links",
            "finalize",
        }
        assert expected_nodes.issubset(nodes), f"Missing: {expected_nodes - nodes}"
