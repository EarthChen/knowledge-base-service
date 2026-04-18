"""Unit tests for wiki.disk_exporter — disk export orchestration."""

from __future__ import annotations

import tempfile
from pathlib import Path

from wiki.disk_exporter import WikiDiskExporter, ExportResult
from wiki.exporter import WikiExporter
from wiki.models import (
    PageType,
    SourceLocation,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
)


def _loc(
    file_path: str,
    start: int,
    end: int,
    fqn: str,
    repo: str = "demo",
) -> SourceLocation:
    return SourceLocation(
        file_path=file_path,
        start_line=start,
        end_line=end,
        fqn=fqn,
        repository=repo,
    )


def _meta() -> WikiPageMetadata:
    return WikiPageMetadata(node_count=3, edge_count=2)


def _structure_simple() -> WikiStructure:
    root = WikiStructureNode(
        path="repo/",
        title="demo",
        page_type=PageType.REPO_OVERVIEW,
        children=[
            WikiStructureNode(
                path="modules/a.md",
                title="Module A",
                page_type=PageType.MODULE_OVERVIEW,
                children=[],
            ),
        ],
    )
    return WikiStructure(repository="demo", root=root, total_pages=1)


class TestWikiDiskExporter:
    def test_export_creates_files(self) -> None:
        structure = WikiStructure(
            repository="demo",
            root=WikiStructureNode(path="/", title="demo", page_type=PageType.REPO_OVERVIEW, children=[]),
            total_pages=2,
        )
        pages = [
            WikiPage(
                path="alpha/one.md",
                title="One",
                page_type=PageType.MODULE_OVERVIEW,
                content="First.",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
            WikiPage(
                path="beta/two.md",
                title="Two",
                page_type=PageType.MODULE_OVERVIEW,
                content="Second.",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = WikiDiskExporter(WikiExporter()).export_to_disk(pages, structure, tmp)
            assert Path(tmp, "alpha", "one.md").exists()
            assert Path(tmp, "beta", "two.md").exists()
            assert isinstance(result, ExportResult)
            assert len(result.files_created) >= 3

    def test_export_index_generated(self) -> None:
        structure = _structure_simple()
        pages = [
            WikiPage(
                path="modules/a.md",
                title="Module A",
                page_type=PageType.MODULE_OVERVIEW,
                content="Mod body.",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            WikiDiskExporter(WikiExporter()).export_to_disk(pages, structure, tmp)
            idx = Path(tmp, "index.md")
            assert idx.exists()
            text = idx.read_text(encoding="utf-8")
            assert "#" in text
            assert "Module A" in text or "modules/a.md" in text

    def test_export_cross_refs_applied(self) -> None:
        structure = WikiStructure(
            repository="demo",
            root=WikiStructureNode(path="/", title="demo", page_type=PageType.REPO_OVERVIEW, children=[]),
            total_pages=2,
        )
        pages = [
            WikiPage(
                path="pkg/nested/a.md",
                title="A",
                page_type=PageType.CLASS_DETAIL,
                content="Link to B.",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
            WikiPage(
                path="pkg/sub/b.md",
                title="B",
                page_type=PageType.CLASS_DETAIL,
                content="B page.",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            WikiDiskExporter(WikiExporter()).export_to_disk(pages, structure, tmp)
            body = Path(tmp, "pkg", "nested", "a.md").read_text(encoding="utf-8")
        assert "[B](" in body
        assert "../sub/b.md" in body

    def test_export_result_stats(self) -> None:
        structure = WikiStructure(
            repository="demo",
            root=WikiStructureNode(path="/", title="demo", page_type=PageType.REPO_OVERVIEW, children=[]),
            total_pages=1,
        )
        pages = [
            WikiPage(
                path="only.md",
                title="Only",
                page_type=PageType.CLASS_DETAIL,
                content="x",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = WikiDiskExporter(WikiExporter()).export_to_disk(pages, structure, tmp)
            index_p = Path(result.index_path)
            assert index_p.name == "index.md"
            total_disk = sum(Path(p).stat().st_size for p in result.files_created)
            assert result.total_size_bytes == total_disk
            assert len(result.files_created) == 2

    def test_export_nested_dirs(self) -> None:
        structure = WikiStructure(
            repository="demo",
            root=WikiStructureNode(path="/", title="demo", page_type=PageType.REPO_OVERVIEW, children=[]),
            total_pages=1,
        )
        pages = [
            WikiPage(
                path="deep/nested/path/page.md",
                title="Deep",
                page_type=PageType.MODULE_OVERVIEW,
                content="Nested page body.",
                diagrams=[],
                source_locations=[_loc("src/X.java", 1, 5, "x.Deep")],
                metadata=_meta(),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            WikiDiskExporter(WikiExporter()).export_to_disk(pages, structure, tmp)
            p = Path(tmp, "deep", "nested", "path", "page.md")
            assert p.exists()
            assert "Nested page body." in p.read_text(encoding="utf-8")
