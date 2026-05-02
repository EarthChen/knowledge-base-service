"""Unit tests for :class:`WikiExportService` (generation bundle shape)."""

from __future__ import annotations

from wiki.export_service import WikiExportService
from wiki.models import PageType, WikiPage, WikiPageMetadata, WikiStructure, WikiStructureNode


def _minimal_page(path: str = "wiki/a.md", title: str = "Page A") -> WikiPage:
    meta = WikiPageMetadata(node_count=0, edge_count=0)
    return WikiPage(
        path=path,
        title=title,
        page_type=PageType.MODULE_OVERVIEW,
        content="# Body",
        diagrams=[],
        source_locations=[],
        metadata=meta,
    )


def _minimal_structure(repo: str = "my-repo") -> WikiStructure:
    root = WikiStructureNode(path="root", title="Root", page_type=PageType.REPO_OVERVIEW)
    return WikiStructure(repository=repo, root=root, total_pages=1)


def test_bundle_markdown_single_page_shape() -> None:
    svc = WikiExportService()
    pages = [_minimal_page()]
    structure = _minimal_structure()
    out = svc.bundle_generation_result(
        pages, structure, export_format="markdown", degraded=False,
    )
    assert out["format"] == "markdown"
    assert out["degraded"] is False
    assert "# Page A" in out["content"]
    assert "Body" in out["content"]


def test_bundle_json_multi_page_uses_exporter_stats() -> None:
    svc = WikiExportService()
    pages = [_minimal_page("wiki/a.md", "A"), _minimal_page("wiki/b.md", "B")]
    structure = _minimal_structure()
    out = svc.bundle_generation_result(
        pages, structure, export_format="json", degraded=True,
    )
    assert out["degraded"] is True
    assert out["stats"]["total_pages"] == 2
    assert len(out["pages"]) == 2
    assert out["structure"]["repository"] == "my-repo"


def test_bundle_json_when_format_markdown_but_multiple_pages() -> None:
    svc = WikiExportService()
    pages = [_minimal_page("wiki/a.md", "A"), _minimal_page("wiki/b.md", "B")]
    structure = _minimal_structure()
    out = svc.bundle_generation_result(
        pages, structure, export_format="markdown", degraded=False,
    )
    assert "pages" in out
    assert out["stats"]["total_pages"] == 2
