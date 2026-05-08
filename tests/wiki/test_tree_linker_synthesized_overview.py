"""Verify tree_linker uses synthesize_overview_from_children."""


def test_tree_linker_uses_overview_synthesizer():
    """tree_linker must import and use synthesize_overview_from_children."""
    with open("wiki/tree_linker.py") as f:
        source = f.read()
    assert "overview_synthesizer" in source or "synthesize_overview_from_children" in source, (
        "tree_linker must import and use overview_synthesizer"
    )
