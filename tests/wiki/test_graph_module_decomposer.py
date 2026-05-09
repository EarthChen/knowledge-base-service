import pytest
from wiki.graph_module_decomposer import make_canonical_key


def test_canonical_key_from_single_path():
    key = make_canonical_key(["src/auth/login.py"], existing_keys=set())
    assert key == "src-auth-login.py"


def test_canonical_key_from_multiple_paths():
    key = make_canonical_key(
        ["src/auth/login.py", "src/auth/register.py"],
        existing_keys=set(),
    )
    assert key == "src-auth"


def test_canonical_key_collision_appends_hash():
    key1 = make_canonical_key(["src/auth/a.py"], existing_keys=set())
    key2 = make_canonical_key(
        ["src/auth/b.py"],
        existing_keys={key1},
        entity_uids=["uid-b"],
    )
    assert key2 != key1
    assert key2.startswith("src-auth")


def test_canonical_key_empty_paths():
    key = make_canonical_key([], existing_keys=set())
    assert key == "unknown"


from wiki.graph_module_decomposer import GraphModuleDecomposer


def _make_graph_data():
    """Simulated dependency graph: A→B, B→C, C→A (cycle), D→A (entry)."""
    return {
        "nodes": ["A", "B", "C", "D"],
        "edges": [("A", "B"), ("B", "C"), ("C", "A"), ("D", "A")],
        "node_files": {
            "A": ["src/a.py"],
            "B": ["src/b.py"],
            "C": ["src/c.py"],
            "D": ["src/d.py"],
        },
        "node_tokens": {"A": 1000, "B": 1000, "C": 1000, "D": 500},
    }


def test_scc_merges_cycle():
    graph = _make_graph_data()
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    sccs = decomposer._compute_scc(graph["nodes"], graph["edges"])
    cycle_scc = [s for s in sccs if len(s) > 1]
    assert len(cycle_scc) == 1
    assert set(cycle_scc[0]) == {"A", "B", "C"}


def test_topological_sort_entry_first():
    graph = _make_graph_data()
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    sccs = decomposer._compute_scc(graph["nodes"], graph["edges"])
    condensed_nodes, condensed_edges = decomposer._condense_graph(
        graph["nodes"], graph["edges"], sccs,
    )
    topo = decomposer._topological_sort(condensed_nodes, condensed_edges)
    assert len(topo) == 2  # {A,B,C} and {D}


def test_decompose_produces_deterministic_tree():
    graph = _make_graph_data()
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    tree1 = decomposer.decompose_from_graph(
        graph["nodes"], graph["edges"],
        graph["node_files"], graph["node_tokens"],
        repo_id="test",
    )
    tree2 = decomposer.decompose_from_graph(
        graph["nodes"], graph["edges"],
        graph["node_files"], graph["node_tokens"],
        repo_id="test",
    )
    keys1 = [n.canonical_key for n in tree1.topological_order()]
    keys2 = [n.canonical_key for n in tree2.topological_order()]
    assert keys1 == keys2  # deterministic


def test_decompose_isolated_nodes():
    """Nodes with no edges each become their own module."""
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    tree = decomposer.decompose_from_graph(
        ["X", "Y", "Z"], [],
        {"X": ["x.py"], "Y": ["y.py"], "Z": ["z.py"]},
        {"X": 100, "Y": 200, "Z": 300},
        repo_id="test",
    )
    assert len(tree.roots) == 3
    assert all(r.is_leaf() for r in tree.roots)


def test_find_connected_components_two_clusters():
    """Two disconnected groups should yield two components."""
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    members = ["A", "B", "C", "D"]
    edges = [("A", "B"), ("C", "D")]
    components = decomposer._find_connected_components(members, edges)
    assert len(components) == 2
    component_sets = [set(c) for c in components]
    assert {"A", "B"} in component_sets
    assert {"C", "D"} in component_sets


def test_find_connected_components_single_cluster():
    """Fully connected members should yield one component."""
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    members = ["A", "B", "C"]
    edges = [("A", "B"), ("B", "C")]
    components = decomposer._find_connected_components(members, edges)
    assert len(components) == 1
    assert set(components[0]) == {"A", "B", "C"}


def test_find_connected_components_isolated_nodes():
    """Nodes with no edges should each be their own component."""
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    members = ["X", "Y", "Z"]
    edges = []
    components = decomposer._find_connected_components(members, edges)
    assert len(components) == 3
