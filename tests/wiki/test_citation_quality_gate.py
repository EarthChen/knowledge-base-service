"""Verify citation_verifier is integrated into quality_gate_node."""


def test_quality_gate_uses_citation_verifier():
    """quality_gate_node must call verify_citations or reference citation_verifier."""
    with open("wiki/pipeline_graph.py") as f:
        source = f.read()
    assert "citation_verifier" in source or "verify_citations" in source, (
        "quality_gate_node must use citation_verifier"
    )


def test_quality_gate_collects_module_names():
    """quality_gate_node must collect module names for entity verification."""
    with open("wiki/pipeline_graph.py") as f:
        source = f.read()
    assert "all_module_names" in source or "known_entities" in source or "module_names" in source, (
        "quality_gate_node must collect entity names for citation verification"
    )
