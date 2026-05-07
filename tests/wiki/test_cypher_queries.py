"""Verify Cypher query constants are correctly exposed."""
from wiki.cypher_queries import (
    METHODS_CY,
    METHOD_CALL_CHAIN_CY,
    ENUMS_CY,
    SNIPPETS_CY,
    CHUNK_SNIPPETS_CY,
    IMPLEMENTS_CY,
    CALLERS_CY,
    FUNCTION_CALLS_CY,
    call_chain_cypher,
)

def test_all_queries_are_non_empty_strings():
    for name, cy in [
        ("METHODS_CY", METHODS_CY),
        ("METHOD_CALL_CHAIN_CY", METHOD_CALL_CHAIN_CY),
        ("ENUMS_CY", ENUMS_CY),
        ("SNIPPETS_CY", SNIPPETS_CY),
        ("CHUNK_SNIPPETS_CY", CHUNK_SNIPPETS_CY),
        ("IMPLEMENTS_CY", IMPLEMENTS_CY),
        ("CALLERS_CY", CALLERS_CY),
        ("FUNCTION_CALLS_CY", FUNCTION_CALLS_CY),
    ]:
        assert isinstance(cy, str), f"{name} should be str"
        assert len(cy) > 20, f"{name} should be non-trivial"
        assert "$names" in cy, f"{name} should use $names param"

def test_call_chain_cypher_depth():
    cy = call_chain_cypher(3)
    assert "CALLS*1..3" in cy
    cy2 = call_chain_cypher(0)
    assert "CALLS*1..1" in cy2

def test_function_calls_cy_has_module_columns():
    assert "caller_module" in FUNCTION_CALLS_CY
    assert "callee_module" in FUNCTION_CALLS_CY

def test_backward_compat_imports():
    from wiki.content_context_builder import _IMPLEMENTS_CY, _CALLERS_CY, _SNIPPETS_CY
    assert "IMPLEMENTS" in _IMPLEMENTS_CY
    assert "caller_name" in _CALLERS_CY
    assert "code_snippet" in _SNIPPETS_CY
