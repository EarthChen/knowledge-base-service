"""Test that decompose_hierarchy_node loads real graph edges when graph_store is available."""
import ast
import inspect

import pytest


def test_decompose_hierarchy_node_does_not_hardcode_empty_edges():
    """Source code should NOT contain 'edges=[]' in decompose_hierarchy_node."""
    from wiki.nodes import classify as classify_mod

    source = inspect.getsource(classify_mod.decompose_hierarchy_node)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "edges":
            if isinstance(node.value, ast.List) and len(node.value.elts) == 0:
                pytest.fail(
                    "decompose_hierarchy_node still contains hardcoded 'edges=[]'. "
                    "It should load real edges from graph_store via ModuleDependencyGraph.build()."
                )


def test_decompose_hierarchy_node_imports_module_dependency_graph():
    """Source should reference ModuleDependencyGraph for loading real edges."""
    from wiki.nodes import classify as classify_mod

    source = inspect.getsource(classify_mod.decompose_hierarchy_node)
    assert "ModuleDependencyGraph" in source, (
        "decompose_hierarchy_node should use ModuleDependencyGraph to load real graph edges"
    )
