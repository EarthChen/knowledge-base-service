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
