import ast


def test_index_full_calls_supplement_contains():
    """The index_full method must call supplement_contains_relationships after enrichment."""
    with open("indexer/incremental_indexer.py") as f:
        source = f.read()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "index_full":
            body_src = ast.get_source_segment(source, node)
            assert "supplement_contains_relationships" in body_src, (
                "index_full must call supplement_contains_relationships"
            )
            enrich_pos = body_src.find("enricher.enrich()")
            supplement_pos = body_src.find("supplement_contains_relationships")
            assert supplement_pos > enrich_pos, (
                "supplement_contains_relationships must come after graph enrichment"
            )
            return
    raise AssertionError("index_full method not found")
