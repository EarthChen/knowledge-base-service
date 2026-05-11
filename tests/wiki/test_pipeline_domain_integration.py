"""Integration tests: domain classification nodes wired into pipeline."""
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
