"""Verify compose_leaf_pages_node uses topological ordering."""


def test_compose_leaf_pages_uses_topo_sort():
    """compose_leaf_pages_node must import and use topological_order."""
    with open("wiki/pipeline_nodes.py") as f:
        source = f.read()
    assert "topo_sort" in source or "topological_order" in source, (
        "pipeline_nodes.py must use topological_order for domain ordering"
    )
