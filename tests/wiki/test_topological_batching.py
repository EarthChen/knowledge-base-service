from wiki.topological_sort import topological_batches


def test_no_edges_single_batch():
    """All nodes independent → one big batch."""
    nodes = ["A", "B", "C"]
    edges = []
    batches = topological_batches(nodes, edges)
    assert len(batches) == 1
    assert set(batches[0]) == {"A", "B", "C"}


def test_linear_chain():
    """A → B → C produces 3 batches."""
    nodes = ["A", "B", "C"]
    edges = [("B", "A"), ("C", "B")]
    batches = topological_batches(nodes, edges)
    assert len(batches) == 3
    assert batches[0] == ["A"]
    assert batches[1] == ["B"]
    assert batches[2] == ["C"]


def test_diamond():
    """Diamond: D depends on B,C; B,C depend on A."""
    nodes = ["A", "B", "C", "D"]
    edges = [("B", "A"), ("C", "A"), ("D", "B"), ("D", "C")]
    batches = topological_batches(nodes, edges)
    assert batches[0] == ["A"]
    assert set(batches[1]) == {"B", "C"}
    assert batches[2] == ["D"]


def test_cycle_handled():
    """Cycles should not cause infinite loop; nodes in cycle go to last batch."""
    nodes = ["A", "B"]
    edges = [("A", "B"), ("B", "A")]
    batches = topological_batches(nodes, edges)
    assert len(batches) >= 1
    all_nodes = [n for batch in batches for n in batch]
    assert set(all_nodes) == {"A", "B"}


def test_mixed_independent_and_dependent():
    nodes = ["X", "Y", "Z", "W"]
    edges = [("Z", "X")]  # Z depends on X; Y and W are independent
    batches = topological_batches(nodes, edges)
    assert "X" in batches[0]
    assert "Y" in batches[0]
    assert "W" in batches[0]
    assert "Z" not in batches[0]
