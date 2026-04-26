# tests/wiki/integration/test_phase5_smoke.py
"""Phase 5 integration smoke tests."""


def test_phase5_imports():
    from wiki import (
        WikiLinkConverter,
        BusinessWikiExporter,
        ExportFile,
        ExportPlan,
        ObsidianExporter,
        MkDocsExporter,
        GitPublisher,
        PublishResult,
    )
    assert WikiLinkConverter is not None
    assert BusinessWikiExporter is not None
    assert ExportFile is not None
    assert ExportPlan is not None
    assert ObsidianExporter is not None
    assert MkDocsExporter is not None
    assert GitPublisher is not None
    assert PublishResult is not None


def test_wikilink_roundtrip():
    from wiki.wikilink_converter import WikiLinkConverter
    conv = WikiLinkConverter()
    original = "See [[/domain/page]]."
    md = conv.to_markdown(original, "/other/current")
    assert "[[" not in md
    assert ".md" in md
    obsidian = conv.to_obsidian(original)
    assert "[[domain/page]]" in obsidian


def test_config_phase5_fields():
    from config import Settings
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    wiki = s.wiki
    assert hasattr(wiki, "git_publish_enabled")
    assert hasattr(wiki, "git_publish_mode")
    assert hasattr(wiki, "git_remote_url")
    assert hasattr(wiki, "git_branch")
    assert hasattr(wiki, "git_author_name")
    assert hasattr(wiki, "export_default_view")
    assert hasattr(wiki, "export_min_tier")
    assert hasattr(wiki, "export_dir_naming")


def test_export_plan_dataclass():
    from wiki.business_wiki_exporter import ExportFile, ExportPlan
    plan = ExportPlan(business_id="test", view="business_domain")
    plan.files.append(ExportFile(relative_path="README.md", content="# Test"))
    assert len(plan.files) == 1
    assert plan.total_pages == 0


def test_publish_result_dataclass():
    from wiki.git_publisher import PublishResult
    result = PublishResult(
        success=True, files_added=1, files_modified=0, files_deleted=0,
        commit_sha="abc123",
    )
    assert result.success
    assert result.commit_sha == "abc123"


def test_obsidian_inherits_business_exporter():
    from wiki.obsidian_exporter import ObsidianExporter
    from wiki.business_wiki_exporter import BusinessWikiExporter
    assert issubclass(ObsidianExporter, BusinessWikiExporter)


def test_mkdocs_inherits_business_exporter():
    from wiki.mkdocs_exporter import MkDocsExporter
    from wiki.business_wiki_exporter import BusinessWikiExporter
    assert issubclass(MkDocsExporter, BusinessWikiExporter)
