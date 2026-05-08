# tests/wiki/test_ccb_call_chain_cypher.py
from wiki.cypher_queries import call_chain_cypher, METHOD_CALL_CHAIN_CY


def test_call_chain_cypher_uses_function_aggregation():
    """New query should go through Function CALLS, not Module CALLS."""
    cypher = call_chain_cypher(3)
    assert "Function" in cypher, "Should query through Function nodes"
    assert "CONTAINS" in cypher, "Should use CONTAINS to link Module->Function"


def test_call_chain_cypher_returns_caller_callee():
    """Should return caller and callee module names."""
    cypher = call_chain_cypher(2)
    assert "caller" in cypher.lower()
    assert "callee" in cypher.lower()


def test_method_call_chain_still_works():
    """METHOD_CALL_CHAIN_CY should still be valid Cypher."""
    assert "CALLS" in METHOD_CALL_CHAIN_CY
    assert "Function" in METHOD_CALL_CHAIN_CY
