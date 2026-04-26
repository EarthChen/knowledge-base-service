from store.schema import NodeLabel, EdgeType


def test_wiki_space_label_exists():
    assert NodeLabel.WIKI_SPACE == "WikiSpace"


def test_wiki_section_label_exists():
    assert NodeLabel.WIKI_SECTION == "WikiSection"


def test_has_child_edge_exists():
    assert EdgeType.HAS_CHILD == "HAS_CHILD"


def test_wiki_references_edge_exists():
    assert EdgeType.WIKI_REFERENCES == "WIKI_REFERENCES"


def test_source_entity_edge_exists():
    assert EdgeType.SOURCE_ENTITY == "SOURCE_ENTITY"
