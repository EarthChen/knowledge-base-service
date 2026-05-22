"""Integration test: reassemble_domains is wired into the pipeline graph."""
from __future__ import annotations


class TestReassemblyPipelineWiring:
    def test_reassemble_node_exists_in_graph(self):
        from wiki.pipeline_graph import build_wiki_pipeline

        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "reassemble_domains" in node_names

    def test_reassemble_between_parent_pages_and_quality_gate(self):
        from wiki.pipeline_graph import build_wiki_pipeline

        pipeline = build_wiki_pipeline(checkpointer=False)
        graph_data = pipeline.get_graph()
        # Check that compose_parent_pages connects to reassemble_domains
        # and reassemble_domains connects to quality_gate
        edges = set()
        for edge in graph_data.edges:
            edges.add((edge.source, edge.target))
        assert ("compose_parent_pages", "reassemble_domains") in edges
        assert ("reassemble_domains", "quality_gate") in edges
        # Old direct edge should NOT exist
        assert ("compose_parent_pages", "quality_gate") not in edges
