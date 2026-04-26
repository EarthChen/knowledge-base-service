from wiki.models import EnrichmentLevel


def test_enrichment_level_values():
    assert EnrichmentLevel.BASE == "base"
    assert EnrichmentLevel.ENRICHED == "enriched"
    assert EnrichmentLevel.ENCYCLOPEDIA == "encyclopedia"


def test_enrichment_level_ordering():
    levels = [EnrichmentLevel.ENCYCLOPEDIA, EnrichmentLevel.BASE, EnrichmentLevel.ENRICHED]
    sorted_levels = sorted(levels, key=lambda x: list(EnrichmentLevel).index(x))
    assert sorted_levels == [EnrichmentLevel.BASE, EnrichmentLevel.ENRICHED, EnrichmentLevel.ENCYCLOPEDIA]


def test_wiki_page_metadata_enrichment_level():
    from wiki.models import WikiPageMetadata

    meta = WikiPageMetadata(node_count=5, edge_count=3, enrichment_level="base")
    assert meta.enrichment_level == "base"


def test_wiki_page_metadata_enrichment_level_default():
    from wiki.models import WikiPageMetadata

    meta = WikiPageMetadata(node_count=5, edge_count=3)
    assert meta.enrichment_level is None
