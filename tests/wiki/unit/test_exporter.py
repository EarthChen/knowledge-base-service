"""Unit tests for wiki.exporter — T2.1 WikiExporter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from wiki.exporter import WikiExporter
from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiDiagram,
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


class TestExportJson:
    def test_export_json(self) -> None:
        pages = [
            WikiPage(
                path="classes/Foo.md",
                title="Foo",
                page_type=PageType.CLASS_DETAIL,
                content="Hello Foo.",
                diagrams=[],
                source_locations=[_loc("src/Foo.java", 1, 10, "com.example.Foo")],
                metadata=_meta(),
            )
        ]
        structure = _structure_simple()
        exporter = WikiExporter()
        out = exporter.export_json(pages, structure)

        json.dumps(out)
        assert "pages" in out
        assert "structure" in out
        assert "stats" in out
        assert len(out["pages"]) == 1
        assert out["pages"][0]["title"] == "Foo"
        assert out["structure"]["repository"] == "demo"

    def test_export_json_stats(self) -> None:
        pages = [
            WikiPage(
                path="a.md",
                title="A",
                page_type=PageType.CLASS_DETAIL,
                content="x",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
            WikiPage(
                path="b.md",
                title="B",
                page_type=PageType.CLASS_DETAIL,
                content="y",
                diagrams=[],
                source_locations=[],
                metadata=_meta(),
            ),
        ]
        structure = WikiStructure(
            repository="r",
            root=WikiStructureNode(path="/", title="r", page_type=PageType.REPO_OVERVIEW, children=[]),
            total_pages=2,
        )
        out = WikiExporter().export_json(pages, structure)
        stats = out["stats"]
        assert stats["total_pages"] == 2
        assert "generation_time_ms" in stats

    def test_source_location_in_export(self) -> None:
        loc = _loc("src/X.java", 5, 20, "com.example.X")
        page = WikiPage(
            path="classes/X.md",
            title="X",
            page_type=PageType.CLASS_DETAIL,
            content="Body.",
            diagrams=[],
            source_locations=[loc],
            metadata=_meta(),
        )
        structure = WikiStructure(
            repository="demo",
            root=WikiStructureNode(path="/", title="demo", page_type=PageType.REPO_OVERVIEW, children=[]),
            total_pages=1,
        )
        out = WikiExporter().export_json([page], structure)
        sl = out["pages"][0]["source_locations"][0]
        assert sl["file_path"] == "src/X.java"
        assert sl["fqn"] == "com.example.X"


class TestExportMarkdownSingle:
    def test_export_markdown_single(self) -> None:
        page = WikiPage(
            path="classes/UserService.md",
            title="UserService",
            page_type=PageType.CLASS_DETAIL,
            content="Overview paragraph.",
            diagrams=[
                WikiDiagram(
                    diagram_type=DiagramType.CLASS_DIAGRAM,
                    content="classDiagram\n  A <|-- B",
                    title="Diagram One",
                )
            ],
            source_locations=[
                _loc("src/UserService.java", 10, 100, "com.example.UserService"),
            ],
            method_locations=[
                _loc("src/UserService.java", 40, 55, "com.example.UserService.save"),
            ],
            metadata=_meta(),
        )
        md = WikiExporter().export_markdown_single(page)
        assert "# UserService" in md
        assert "Overview paragraph." in md
        assert "```mermaid" in md
        assert "classDiagram" in md
        assert "Diagram One" in md
        assert "src/UserService.java" in md
        assert "save" in md or "UserService.save" in md or "40" in md


class TestExportMarkdownFileset:
    def test_export_markdown_fileset(self) -> None:
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
            created = WikiExporter().export_markdown_fileset(pages, structure, tmp)
            assert len(created) == 2
            for p in created:
                assert Path(p).exists()
            assert Path(tmp, "alpha", "one.md").read_text(encoding="utf-8")
            assert Path(tmp, "beta", "two.md").read_text(encoding="utf-8")


class TestAutoLinkCrossReferences:
    def test_auto_link_cross_references(self) -> None:
        content = "See Bar for details."
        entity_map = {"Bar": "classes/Bar.md"}
        out = WikiExporter().auto_link_cross_references(content, entity_map)
        assert "[Bar](classes/Bar.md)" in out

    def test_auto_link_skip_self(self) -> None:
        current = "classes/Foo.md"
        entity_map = {"Foo": current, "Bar": "classes/Bar.md"}
        filtered = {k: v for k, v in entity_map.items() if v != current}
        content = "Foo uses Bar."
        out = WikiExporter().auto_link_cross_references(content, filtered)
        assert "[Bar](classes/Bar.md)" in out
        assert "[Foo]" not in out

    def test_auto_link_no_match(self) -> None:
        content = "Nothing recognizable here."
        entity_map = {"OtherEntity": "classes/Other.md"}
        out = WikiExporter().auto_link_cross_references(content, entity_map)
        assert out == content


class TestPathDeduplication:
    def test_resolve_unique_paths_fqn_on_collision(self) -> None:
        a = WikiPage(
            path="classes/Service.md",
            title="Service",
            page_type=PageType.CLASS_DETAIL,
            content="A",
            diagrams=[],
            source_locations=[_loc("a.java", 1, 2, "com.foo.Service")],
            metadata=_meta(),
        )
        b = WikiPage(
            path="classes/Service.md",
            title="Service",
            page_type=PageType.CLASS_DETAIL,
            content="B",
            diagrams=[],
            source_locations=[_loc("b.java", 1, 2, "com.bar.Service")],
            metadata=_meta(),
        )
        exporter = WikiExporter()
        resolved = exporter._resolve_unique_paths([a, b])
        paths = {resolved[id(a)], resolved[id(b)]}
        assert len(paths) == 2
        assert paths == {"classes/com.foo.Service.md", "classes/com.bar.Service.md"}

    def test_collision_same_fqn_slug_triggers_numeric_suffix(self) -> None:
        dup_fqn = "same.pkg.Dupe"
        a = WikiPage(
            path="classes/X.md",
            title="Dupe",
            page_type=PageType.CLASS_DETAIL,
            content="A",
            diagrams=[],
            source_locations=[_loc("a.java", 1, 2, dup_fqn)],
            metadata=_meta(),
        )
        b = WikiPage(
            path="classes/X.md",
            title="Dupe",
            page_type=PageType.CLASS_DETAIL,
            content="B",
            diagrams=[],
            source_locations=[_loc("b.java", 1, 2, dup_fqn)],
            metadata=_meta(),
        )
        exporter = WikiExporter()
        resolved = exporter._resolve_unique_paths([a, b])
        assert resolved[id(a)] != resolved[id(b)]

    def test_slug_fqn_root_relative_parent(self) -> None:
        from wiki.exporter import _slug_fqn_path

        assert _slug_fqn_path("Svc.md", "com.example.Service") == "com.example.Service.md"


class TestBuildEntityPageMap:
    def test_duplicate_title_maps_fqn_keys(self) -> None:
        pages = [
            WikiPage(
                path="classes/Foo.md",
                title="Foo",
                page_type=PageType.CLASS_DETAIL,
                content="",
                diagrams=[],
                source_locations=[_loc("a.java", 1, 2, "pkg.one.Foo")],
                metadata=_meta(),
            ),
            WikiPage(
                path="classes/Foo.md",
                title="Foo",
                page_type=PageType.CLASS_DETAIL,
                content="",
                diagrams=[],
                source_locations=[_loc("b.java", 1, 2, "pkg.two.Foo")],
                metadata=_meta(),
            ),
        ]
        exporter = WikiExporter()
        resolved = exporter._resolve_unique_paths(pages)
        m = WikiExporter.build_entity_page_map(pages, resolved)
        assert "pkg.one.Foo" in m
        assert "pkg.two.Foo" in m

    def test_entity_map_without_explicit_paths_uses_resolver(self) -> None:
        page = WikiPage(
            path="only.md",
            title="Only",
            page_type=PageType.CLASS_DETAIL,
            content="",
            diagrams=[],
            source_locations=[],
            metadata=_meta(),
        )
        m = WikiExporter.build_entity_page_map([page])
        assert m["Only"] == "only.md"


class TestAutoLinkFqn:
    def test_auto_link_non_identifier_fqn_key(self) -> None:
        content = "Uses pkg.one.Service in code."
        entity_map = {"pkg.one.Service": "classes/Svc.md"}
        out = WikiExporter().auto_link_cross_references(content, entity_map)
        assert "[pkg.one.Service](classes/Svc.md)" in out

    def test_auto_link_empty_entity_map_returns_unchanged(self) -> None:
        assert WikiExporter.auto_link_cross_references("hello", {}) == "hello"


class TestRelativeLinks:
    def test_export_relative_links(self) -> None:
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
            WikiExporter().export_markdown_fileset(pages, structure, tmp)
            body = Path(tmp, "pkg", "nested", "a.md").read_text(encoding="utf-8")
        assert "[B](" in body
        rel = "../sub/b.md"
        assert rel in body
