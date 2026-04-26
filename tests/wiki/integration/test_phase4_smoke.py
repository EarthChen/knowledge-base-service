"""Phase 4 integration smoke test — verify all new components are importable and wired."""
import pytest


def test_phase4_imports():
    """All Phase 4 components should be importable from wiki package."""
    from wiki import (
        CrossRepoBusinessDomainPlanner,
        WikiReferenceGenerator,
        DomainOverviewComposer,
        WikiTreeBuilder,
    )

    assert CrossRepoBusinessDomainPlanner is not None
    assert WikiReferenceGenerator is not None
    assert DomainOverviewComposer is not None
    assert WikiTreeBuilder is not None


def test_page_type_domain_overview_exists():
    """PageType should have DOMAIN_OVERVIEW value."""
    from wiki.models import PageType

    assert hasattr(PageType, "DOMAIN_OVERVIEW")
    assert PageType.DOMAIN_OVERVIEW == "domain_overview"


def test_config_phase4_fields_exist():
    """Phase 4 config fields should be accessible."""
    from config import Settings

    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert hasattr(s.wiki, "cross_repo_domain_enabled")
    assert hasattr(s.wiki, "business_wiki_batch_threshold")
    assert s.wiki.cross_repo_domain_enabled is False
    assert s.wiki.business_wiki_batch_threshold == 100


def test_wiki_tree_builder_methods():
    """WikiTreeBuilder should have all required methods."""
    from wiki.tree_builder import WikiTreeBuilder

    builder = WikiTreeBuilder()
    assert hasattr(builder, "generate_page_path")
    assert hasattr(builder, "generate_section_uid")
    assert hasattr(builder, "generate_space_uid")
    assert hasattr(builder, "detect_naming_conflicts")
    assert hasattr(builder, "compute_content_hash")
    assert hasattr(builder, "generate_domain_section_uid")
    assert hasattr(builder, "generate_repo_section_uid")


def test_wiki_service_has_business_method():
    """WikiService should have generate_business_wiki method."""
    from wiki.service import WikiService

    assert hasattr(WikiService, "generate_business_wiki")


def test_wiki_mcp_tools_manifest_has_phase4_tools():
    """MCP tools manifest should include Phase 4 tools."""
    from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST

    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_tree" in tool_names
    assert "wiki_get_related" in tool_names
    assert "wiki_get_domain_overview" in tool_names


@pytest.mark.asyncio
async def test_domain_overview_page_serialization():
    """DomainOverviewComposer page should serialize correctly."""
    from wiki.domain_overview_composer import DomainOverviewComposer

    composer = DomainOverviewComposer(llm=None)
    page = await composer.compose("Test Domain", [])
    d = page.to_dict()
    assert d["page_type"] == "domain_overview"
    assert d["path"] == "/Test Domain/_overview"
