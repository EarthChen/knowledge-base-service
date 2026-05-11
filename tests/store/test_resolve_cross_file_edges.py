"""Tests for resolve_cross_file_edges IMPORTS edge retention."""

import inspect

from store.falkordb_reads import FalkorDBReadsMixin


def test_resolve_cross_file_edges_does_not_delete_imports():
    """The IMPORTS edge type should NOT be in the delete loop."""
    source = inspect.getsource(FalkorDBReadsMixin.resolve_cross_file_edges)
    # The delete loop starts with 'for edge_type in ...'
    # IMPORTS should not be in the deletion tuple
    assert '"IMPORTS"' not in source.split("for edge_type")[0] if "for edge_type" in source else True
    # More robust: check the actual tuple
    for_line = [line.strip() for line in source.split("\n") if "for edge_type in" in line]
    assert len(for_line) >= 1, "Should have a 'for edge_type in' loop"
    assert "IMPORTS" not in for_line[0], f"IMPORTS should not be in deletion loop: {for_line[0]}"
