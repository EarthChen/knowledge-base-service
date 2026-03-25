"""Tests for graph schema definitions."""

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel, VECTOR_INDEX_CONFIGS


class TestGraphNode:
    def test_auto_uid_generation(self):
        node = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={"name": "hello", "file": "test.py", "start_line": 10},
        )
        assert node.uid == "Function:test.py:hello:10"

    def test_explicit_uid(self):
        node = GraphNode(
            label=NodeLabel.CLASS,
            properties={"name": "Foo", "file": "bar.py", "start_line": 1},
            uid="custom-uid",
        )
        assert node.uid == "custom-uid"

    def test_uid_with_missing_properties(self):
        node = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "mymodule"},
        )
        assert node.uid == "Module::mymodule:0"

    def test_all_node_labels(self):
        assert NodeLabel.FUNCTION == "Function"
        assert NodeLabel.CLASS == "Class"
        assert NodeLabel.MODULE == "Module"
        assert NodeLabel.DOCUMENT == "Document"


class TestGraphEdge:
    def test_basic_edge(self):
        edge = GraphEdge(
            edge_type=EdgeType.CALLS,
            source_uid="src",
            target_uid="tgt",
        )
        assert edge.edge_type == EdgeType.CALLS
        assert edge.source_uid == "src"
        assert edge.target_uid == "tgt"
        assert edge.properties == {}

    def test_edge_with_properties(self):
        edge = GraphEdge(
            edge_type=EdgeType.IMPORTS,
            source_uid="a",
            target_uid="b",
            properties={"line": 42},
        )
        assert edge.properties["line"] == 42

    def test_all_edge_types(self):
        assert EdgeType.CALLS == "CALLS"
        assert EdgeType.INHERITS == "INHERITS"
        assert EdgeType.IMPORTS == "IMPORTS"
        assert EdgeType.CONTAINS == "CONTAINS"
        assert EdgeType.USES_TYPE == "USES_TYPE"
        assert EdgeType.REFERENCES == "REFERENCES"


class TestVectorIndexConfigs:
    def test_configs_exist(self):
        assert len(VECTOR_INDEX_CONFIGS) == 3

    def test_configs_cover_labels(self):
        labels = {c["label"] for c in VECTOR_INDEX_CONFIGS}
        assert NodeLabel.FUNCTION in labels
        assert NodeLabel.CLASS in labels
        assert NodeLabel.DOCUMENT in labels

    def test_all_use_cosine(self):
        for cfg in VECTOR_INDEX_CONFIGS:
            assert cfg["similarity"] == "cosine"
            assert cfg["attribute"] == "embedding"
