"""Integration tests: domain classification nodes wired into pipeline."""
import os
from unittest.mock import patch

from wiki.pipeline_graph import build_wiki_pipeline


class TestDomainClassificationInPipeline:
    def test_pipeline_contains_classify_domains_node(self):
        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "classify_domains" in node_names

    def test_pipeline_contains_decompose_hierarchy_node(self):
        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "decompose_hierarchy" in node_names


class TestUseAgentComposeSwitch:
    def test_default_uses_compose_bottomup(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USE_AGENT_COMPOSE", None)
            pipeline = build_wiki_pipeline(checkpointer=False)
            nodes = set(pipeline.get_graph().nodes.keys())
            assert "compose_bottomup" in nodes
            assert "compose_domain_agents" not in nodes

    def test_use_agent_compose_true(self):
        with patch.dict(os.environ, {"USE_AGENT_COMPOSE": "true"}):
            pipeline = build_wiki_pipeline(checkpointer=False)
            nodes = set(pipeline.get_graph().nodes.keys())
            assert "compose_domain_agents" in nodes
            assert "compose_bottomup" not in nodes

    def test_use_agent_compose_false(self):
        with patch.dict(os.environ, {"USE_AGENT_COMPOSE": "false"}):
            pipeline = build_wiki_pipeline(checkpointer=False)
            nodes = set(pipeline.get_graph().nodes.keys())
            assert "compose_bottomup" in nodes
            assert "compose_domain_agents" not in nodes


class TestAgentPipelineIntegration:
    def test_full_pipeline_with_agent_compose(self):
        """End-to-end: pipeline with USE_AGENT_COMPOSE=true produces domain pages."""
        with patch.dict(os.environ, {"USE_AGENT_COMPOSE": "true"}):
            pipeline = build_wiki_pipeline(checkpointer=False)
            nodes = set(pipeline.get_graph().nodes.keys())
            expected_nodes = {
                "classify_entity_roles",
                "detect_reorg",
                "graph_decompose",
                "assign_canonical_keys",
                "classify_domains",
                "decompose_hierarchy",
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

    def test_full_pipeline_default_has_compose_bottomup(self):
        """Default pipeline uses compose_bottomup (backward compat)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USE_AGENT_COMPOSE", None)
            pipeline = build_wiki_pipeline(checkpointer=False)
            nodes = set(pipeline.get_graph().nodes.keys())
            expected_nodes = {
                "classify_entity_roles",
                "detect_reorg",
                "graph_decompose",
                "assign_canonical_keys",
                "classify_domains",
                "decompose_hierarchy",
                "generate_titles",
                "set_review_status",
                "compose_leaf_modules",
                "compose_bottomup",
                "quality_gate",
                "heal_pages",
                "create_links",
                "finalize",
            }
            assert expected_nodes.issubset(nodes), f"Missing: {expected_nodes - nodes}"
