"""Test that search_entity_cypher does NOT reference annotations (list field)."""


def test_search_entity_cypher_no_annotations():
    """Cypher template should not use annotations field (it's a list, not string)."""
    from wiki.cypher_queries import search_entity_cypher, SEARCH_ENTITY_LABELS

    for label in SEARCH_ENTITY_LABELS:
        cy = search_entity_cypher(label)
        assert "annotations" not in cy.lower(), (
            f"search_entity_cypher({label}) still references annotations — "
            "this causes 'Type mismatch: expected String or Null but was List' on nodes "
            "where annotations is stored as a List"
        )
