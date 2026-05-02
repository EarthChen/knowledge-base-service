"""Phase 3 integration smoke test — verify all components importable and wired."""
import pytest


def test_phase3_imports():
    """All Phase 3 components should be importable from wiki package."""
    from wiki import (
        AsyncEnrichmentPipeline,
        BusinessDomainPlanner,
        EnrichmentLevel,
        TieredPromptBuilder,
    )

    assert AsyncEnrichmentPipeline is not None
    assert BusinessDomainPlanner is not None
    assert EnrichmentLevel is not None
    assert TieredPromptBuilder is not None


def test_enrichment_level_enum_completeness():
    from wiki.models import EnrichmentLevel

    assert len(EnrichmentLevel) == 3
    assert set(EnrichmentLevel) == {
        EnrichmentLevel.BASE,
        EnrichmentLevel.ENRICHED,
        EnrichmentLevel.ENCYCLOPEDIA,
    }


def test_config_phase3_fields_exist():
    from core.config import Settings

    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert hasattr(s.wiki, "enrichment_enabled")
    assert hasattr(s.wiki, "enrichment_round1_enabled")
    assert hasattr(s.wiki, "enrichment_round2_enabled")
    assert hasattr(s.wiki, "business_domain_enabled")
    assert hasattr(s.wiki, "business_domain_infrastructure_label")


@pytest.mark.asyncio
async def test_wiki_page_to_dict_includes_enrichment_level():
    from wiki.models import EnrichmentLevel, PageType, WikiPage, WikiPageMetadata

    page = WikiPage(
        path="test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content="# Test",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(
            node_count=1,
            edge_count=0,
            enrichment_level=EnrichmentLevel.ENRICHED,
        ),
    )
    d = page.to_dict()
    assert d["metadata"]["enrichment_level"] == "enriched"


@pytest.mark.asyncio
async def test_wiki_page_from_dict_preserves_enrichment_level():
    from wiki.models import WikiPage

    data = {
        "path": "test.md",
        "title": "Test",
        "page_type": "class_detail",
        "content": "# Test",
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "metadata": {
            "node_count": 1,
            "edge_count": 0,
            "generation_mode": "structure",
            "fallback_tier": 3,
            "enrichment_level": "encyclopedia",
        },
    }
    page = WikiPage.from_dict(data)
    assert page.metadata.enrichment_level == "encyclopedia"


@pytest.mark.asyncio
async def test_wiki_page_from_dict_without_enrichment_level():
    """Backward compat: old payloads without enrichment_level should work."""
    from wiki.models import WikiPage

    data = {
        "path": "test.md",
        "title": "Test",
        "page_type": "class_detail",
        "content": "# Test",
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "metadata": {
            "node_count": 1,
            "edge_count": 0,
            "generation_mode": "structure",
            "fallback_tier": 3,
        },
    }
    page = WikiPage.from_dict(data)
    assert page.metadata.enrichment_level is None
