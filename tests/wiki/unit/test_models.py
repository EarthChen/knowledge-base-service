"""Tests for wiki data models — T1.1 Data Models.

TDD RED phase: these tests define the expected interface for wiki/models.py.
"""

from __future__ import annotations

import json

import pytest

from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiConfig,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
    WikiPageQualityScore,
    WikiQualityDimension,
    WikiStructure,
    WikiStructureNode,
    parse_scope,
)


class TestScopeParsing:
    def test_scope_parse_repo(self):
        scope = parse_scope("repo")
        assert scope.scope_type == "repo"
        assert scope.value is None

    def test_scope_parse_module(self):
        scope = parse_scope("module:src/service.py")
        assert scope.scope_type == "module"
        assert scope.value == "src/service.py"

    def test_scope_parse_class(self):
        scope = parse_scope("class:com.example.UserService")
        assert scope.scope_type == "class"
        assert scope.value == "com.example.UserService"

    def test_scope_parse_module_nested_path(self):
        scope = parse_scope("module:com/example/service/impl")
        assert scope.scope_type == "module"
        assert scope.value == "com/example/service/impl"

    def test_scope_parse_invalid_no_type(self):
        with pytest.raises(ValueError, match="scope"):
            parse_scope("invalid")

    def test_scope_parse_invalid_unknown_type(self):
        with pytest.raises(ValueError, match="scope"):
            parse_scope("function:foo")

    def test_scope_parse_empty_value(self):
        with pytest.raises(ValueError, match="scope"):
            parse_scope("module:")

    def test_scope_parse_empty_string(self):
        with pytest.raises(ValueError, match="scope"):
            parse_scope("")

    def test_scope_parse_extra_colons(self):
        scope = parse_scope("class:com.example:UserService")
        assert scope.scope_type == "class"
        assert scope.value == "com.example:UserService"


class TestSourceLocation:
    def test_basic_construction(self):
        loc = SourceLocation(
            file_path="src/service/UserService.java",
            start_line=15,
            end_line=120,
            fqn="com.example.UserService",
            repository="my-repo",
        )
        assert loc.file_path == "src/service/UserService.java"
        assert loc.start_line == 15
        assert loc.end_line == 120
        assert loc.fqn == "com.example.UserService"
        assert loc.repository == "my-repo"

    def test_source_link_format(self):
        loc = SourceLocation(
            file_path="src/UserService.java",
            start_line=15,
            end_line=120,
            fqn="com.example.UserService",
            repository="my-repo",
        )
        link = loc.to_source_link()
        assert "src/UserService.java" in link
        assert "L15" in link

    def test_ide_deep_link_vscode(self):
        loc = SourceLocation(
            file_path="src/UserService.java",
            start_line=15,
            end_line=120,
            fqn="com.example.UserService",
            repository="my-repo",
        )
        link = loc.to_ide_link("vscode", repo_path="/home/user/my-repo")
        assert link.startswith("vscode://file/")
        assert "src/UserService.java" in link
        assert ":15" in link

    def test_ide_deep_link_cursor(self):
        loc = SourceLocation(
            file_path="src/UserService.java",
            start_line=15,
            end_line=120,
            fqn="com.example.UserService",
            repository="my-repo",
        )
        link = loc.to_ide_link("cursor", repo_path="/home/user/my-repo")
        assert link.startswith("cursor://file/")

    def test_ide_deep_link_idea(self):
        loc = SourceLocation(
            file_path="src/UserService.java",
            start_line=15,
            end_line=120,
            fqn="com.example.UserService",
            repository="my-repo",
        )
        link = loc.to_ide_link("idea", repo_path="/home/user/my-repo")
        assert link.startswith("idea://open")
        assert "line=15" in link

    def test_ide_deep_link_unsupported(self):
        loc = SourceLocation(
            file_path="src/UserService.java",
            start_line=15,
            end_line=120,
            fqn="com.example.UserService",
            repository="my-repo",
        )
        with pytest.raises(ValueError, match="Unsupported"):
            loc.to_ide_link("emacs", repo_path="/home/user/my-repo")


class TestWikiConfig:
    def test_defaults(self):
        config = WikiConfig(repository="my-repo")
        assert config.repository == "my-repo"
        assert config.mode == "structure"
        assert config.format == "json"
        assert config.language == "en"

    def test_full_mode(self):
        config = WikiConfig(repository="my-repo", mode="full")
        assert config.mode == "full"

    def test_invalid_mode(self):
        with pytest.raises(ValueError):
            WikiConfig(repository="my-repo", mode="invalid")

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            WikiConfig(repository="my-repo", format="xml")


class TestWikiDiagram:
    def test_basic(self):
        diag = WikiDiagram(
            diagram_type=DiagramType.CLASS_DIAGRAM,
            content="classDiagram\n    Animal <|-- Duck",
            title="Class Hierarchy",
        )
        assert diag.diagram_type == DiagramType.CLASS_DIAGRAM
        assert "classDiagram" in diag.content

    def test_all_diagram_types(self):
        assert DiagramType.CLASS_DIAGRAM == "classDiagram"
        assert DiagramType.FLOWCHART == "flowchart"
        assert DiagramType.DEPENDENCY_GRAPH == "dependencyGraph"
        assert DiagramType.SEQUENCE_DIAGRAM == "sequenceDiagram"
        assert DiagramType.STATE == "stateDiagram-v2"
        assert DiagramType.DATA_FLOW == "dataFlow"
        assert DiagramType.ARCHITECTURE == "architecture"


class TestWikiPageMetadata:
    def test_basic(self):
        meta = WikiPageMetadata(
            node_count=15,
            edge_count=42,
            generation_mode="full",
            fallback_tier=1,
        )
        assert meta.node_count == 15
        assert meta.edge_count == 42
        assert meta.generation_mode == "full"
        assert meta.fallback_tier == 1

    def test_defaults(self):
        meta = WikiPageMetadata(node_count=5, edge_count=10)
        assert meta.generation_mode == "structure"
        assert meta.fallback_tier is None


class TestWikiPage:
    def _make_page(self) -> WikiPage:
        return WikiPage(
            path="classes/UserService.md",
            title="UserService",
            page_type=PageType.CLASS_DETAIL,
            content="# UserService\n\nCore user management service.",
            diagrams=[
                WikiDiagram(
                    diagram_type=DiagramType.CLASS_DIAGRAM,
                    content="classDiagram\n    BaseService <|-- UserService",
                    title="Inheritance",
                )
            ],
            source_locations=[
                SourceLocation(
                    file_path="src/service/UserService.java",
                    start_line=15,
                    end_line=120,
                    fqn="com.example.UserService",
                    repository="my-repo",
                )
            ],
            method_locations=[
                SourceLocation(
                    file_path="src/service/UserService.java",
                    start_line=45,
                    end_line=62,
                    fqn="com.example.UserService.createUser",
                    repository="my-repo",
                )
            ],
            metadata=WikiPageMetadata(node_count=15, edge_count=42),
        )

    def test_construction(self):
        page = self._make_page()
        assert page.path == "classes/UserService.md"
        assert page.title == "UserService"
        assert page.page_type == PageType.CLASS_DETAIL
        assert len(page.diagrams) == 1
        assert len(page.source_locations) == 1
        assert len(page.method_locations) == 1

    def test_to_json(self):
        page = self._make_page()
        data = page.to_dict()
        assert data["path"] == "classes/UserService.md"
        assert data["title"] == "UserService"
        assert "source_locations" in data
        assert data["source_locations"][0]["file_path"] == "src/service/UserService.java"
        json_str = json.dumps(data)
        assert '"UserService"' in json_str

    def test_to_markdown(self):
        page = self._make_page()
        md = page.to_markdown()
        assert "# UserService" in md
        assert "```mermaid" in md
        assert "classDiagram" in md

    def test_page_types(self):
        assert PageType.MODULE_OVERVIEW == "module_overview"
        assert PageType.CLASS_DETAIL == "class_detail"
        assert PageType.REPO_OVERVIEW == "repo_overview"
        assert PageType.ARCHITECTURE == "architecture"
        assert PageType.API_REFERENCE == "api_reference"
        assert PageType.DATA_FLOW == "data_flow"

    def test_empty_diagrams(self):
        page = WikiPage(
            path="modules/service.md",
            title="Service Module",
            page_type=PageType.MODULE_OVERVIEW,
            content="# Service Module",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(node_count=5, edge_count=10),
        )
        md = page.to_markdown()
        assert "```mermaid" not in md

    def test_default_method_locations(self):
        page = WikiPage(
            path="modules/service.md",
            title="Service Module",
            page_type=PageType.MODULE_OVERVIEW,
            content="# Service Module",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(node_count=5, edge_count=10),
        )
        assert page.method_locations == []


class TestWikiStructure:
    def test_basic_structure(self):
        root = WikiStructureNode(
            path="modules/",
            title="Modules",
            page_type=PageType.MODULE_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="modules/service.md",
                    title="Service Module",
                    page_type=PageType.MODULE_OVERVIEW,
                ),
                WikiStructureNode(
                    path="modules/store.md",
                    title="Store Module",
                    page_type=PageType.MODULE_OVERVIEW,
                ),
            ],
        )
        structure = WikiStructure(
            repository="my-repo",
            root=root,
            total_pages=2,
        )
        assert structure.repository == "my-repo"
        assert structure.total_pages == 2
        assert len(structure.root.children) == 2

    def test_children_sorted_alphabetically(self):
        root = WikiStructureNode(
            path="modules/",
            title="Modules",
            page_type=PageType.MODULE_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="modules/zstore.md",
                    title="ZStore Module",
                    page_type=PageType.MODULE_OVERVIEW,
                ),
                WikiStructureNode(
                    path="modules/aservice.md",
                    title="AService Module",
                    page_type=PageType.MODULE_OVERVIEW,
                ),
            ],
        )
        sorted_children = root.sorted_children()
        assert sorted_children[0].title == "AService Module"
        assert sorted_children[1].title == "ZStore Module"

    def test_structure_to_dict(self):
        root = WikiStructureNode(
            path="repo/",
            title="My Repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="modules/service.md",
                    title="Service",
                    page_type=PageType.MODULE_OVERVIEW,
                ),
            ],
        )
        structure = WikiStructure(repository="my-repo", root=root, total_pages=1)
        data = structure.to_dict()
        assert data["repository"] == "my-repo"
        assert data["total_pages"] == 1
        assert "root" in data
        assert len(data["root"]["children"]) == 1


def test_quality_dimension_values():
    assert WikiQualityDimension.COMPLETENESS == "completeness"
    assert WikiQualityDimension.HELPFULNESS == "helpfulness"
    assert WikiQualityDimension.TRUTHFULNESS == "truthfulness"


def test_quality_score_overall():
    score = WikiPageQualityScore(
        page_path="classes/Foo.md",
        completeness=0.8,
        helpfulness=0.7,
        truthfulness=0.9,
        overall=0.8,
        issues=[],
    )
    assert score.overall == 0.8
    assert not score.issues
