"""Unit tests for wiki.page_templates and extended diagram_gen helpers (P2 page types)."""

from __future__ import annotations

import re

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.diagram_gen import (
    generate_data_flow_diagram,
    generate_layered_architecture_diagram,
    generate_module_dependency_flowchart,
)
from wiki.models import DiagramType, PageType, WikiConfig
from wiki.page_templates import WikiPageTemplates
from wiki.repo_composer import ArchitectureLayer


def _cfg(repo: str = "demo-repo") -> WikiConfig:
    return WikiConfig(repository=repo, mode="structure", format="markdown", language="en")


def _mod(name: str, path: str, desc: str = "") -> GraphNode:
    props: dict[str, str | int | float | list[str]] = {"name": name, "path": path, "file": f"{path}/__init__.py"}
    if desc:
        props["description"] = desc
    return GraphNode(label=NodeLabel.MODULE, properties=props, uid=f"mod:{name}")


def _fn(
    name: str,
    file_path: str,
    line: int = 1,
    *,
    visibility: str = "public",
    signature: str = "",
    doc: str = "",
) -> GraphNode:
    props: dict[str, str | int | float | list[str]] = {
        "name": name,
        "file": file_path,
        "start_line": line,
        "end_line": line + 5,
        "fqn": f"m.{name}",
        "visibility": visibility,
    }
    if signature:
        props["signature"] = signature
    if doc:
        props["docstring"] = doc
    return GraphNode(label=NodeLabel.FUNCTION, properties=props, uid=f"Function:{file_path}:{name}:{line}")


class TestArchitectureOverview:
    def test_architecture_overview_has_layer_diagram(self) -> None:
        layers: dict[ArchitectureLayer, list[GraphNode]] = {
            ArchitectureLayer.API: [_mod("api_mod", "api/routes.py", "HTTP")],
            ArchitectureLayer.SERVICE: [_mod("svc", "service/core.py")],
        }
        edges = [
            GraphEdge(EdgeType.IMPORTS, layers[ArchitectureLayer.API][0].uid, layers[ArchitectureLayer.SERVICE][0].uid),
        ]
        tech = {"languages": ["python"], "frameworks": ["fastapi"]}
        page = WikiPageTemplates.render_architecture_overview(
            repository="acme",
            layers=layers,
            inter_module_edges=edges,
            tech_stack=tech,
            config=_cfg("acme"),
        )
        assert page.page_type == PageType.ARCHITECTURE
        joined = page.content + "\n" + "\n".join(d.content for d in page.diagrams)
        assert "graph TD" in joined
        assert "subgraph" in joined.lower() or "subgraph" in joined

    def test_architecture_overview_tech_stack(self) -> None:
        layers = {ArchitectureLayer.SERVICE: [_mod("x", "x.py")]}
        page = WikiPageTemplates.render_architecture_overview(
            repository="r",
            layers=layers,
            inter_module_edges=[],
            tech_stack={"languages": ["python", "java"], "frameworks": []},
            config=_cfg("r"),
        )
        assert "## Technology Stack" in page.content
        assert "python" in page.content.lower() and "java" in page.content.lower()

    def test_architecture_overview_layer_details(self) -> None:
        layers = {
            ArchitectureLayer.API: [_mod("routes", "api/routes.py")],
            ArchitectureLayer.DATA: [_mod("repo", "data/repo.py", "Persistence")],
        }
        page = WikiPageTemplates.render_architecture_overview(
            repository="r",
            layers=layers,
            inter_module_edges=[],
            tech_stack={"languages": [], "frameworks": []},
            config=_cfg("r"),
        )
        assert "## Layer Details" in page.content
        assert "routes" in page.content
        assert "repo" in page.content

    def test_architecture_overview_inter_module_deps(self) -> None:
        a, b = _mod("a", "a.py"), _mod("b", "b.py")
        layers = {ArchitectureLayer.SERVICE: [a, b]}
        edges = [GraphEdge(EdgeType.IMPORTS, a.uid, b.uid)]
        page = WikiPageTemplates.render_architecture_overview(
            repository="r",
            layers=layers,
            inter_module_edges=edges,
            tech_stack={"languages": ["python"], "frameworks": []},
            config=_cfg("r"),
        )
        assert any("flowchart LR" in d.content for d in page.diagrams)


class TestDataFlow:
    def test_data_flow_from_entry_point(self) -> None:
        a = _fn("entry", "src/a.py", 1)
        b = _fn("middle", "src/b.py", 10)
        c = _fn("sink", "src/c.py", 20)
        e1 = GraphEdge(EdgeType.CALLS, a.uid, b.uid)
        e2 = GraphEdge(EdgeType.CALLS, b.uid, c.uid)
        chain: list[tuple[GraphNode, GraphEdge | None]] = [(a, e1), (b, e2), (c, None)]
        page = WikiPageTemplates.render_data_flow(
            flow_name="main",
            entry_point=a,
            call_chain=chain,
            config=_cfg(),
        )
        assert page.page_type == PageType.DATA_FLOW
        flow_d = next((d for d in page.diagrams if "flowchart" in d.content), page.diagrams[0])
        assert flow_d.content.count("[") >= 3
        assert flow_d.content.count("-->") >= 2

    def test_data_flow_no_entry_points(self) -> None:
        a = _fn("orphan", "src/o.py", 1)
        page = WikiPageTemplates.render_data_flow(
            flow_name="empty",
            entry_point=a,
            call_chain=[],
            config=_cfg(),
        )
        assert page.page_type == PageType.DATA_FLOW
        assert "_No call chain" in page.content or "empty" in page.content.lower()

    def test_data_flow_stages_table(self) -> None:
        a = _fn("parse", "p.py", 1)
        b = _fn("transform", "t.py", 2)
        e1 = GraphEdge(EdgeType.CALLS, a.uid, b.uid)
        chain: list[tuple[GraphNode, GraphEdge | None]] = [(a, e1), (b, None)]
        page = WikiPageTemplates.render_data_flow(flow_name="pipe", entry_point=a, call_chain=chain, config=_cfg())
        assert "| Component |" in page.content or "| component |" in page.content.lower()
        assert "parse" in page.content and "transform" in page.content


class TestApiReference:
    def test_api_reference_lists_public(self) -> None:
        mod = _mod("svc", "service/")
        pubs = [_fn(f"p{i}", "s.py", i, visibility="public") for i in range(3)]
        priv = [_fn(f"x{i}", "s.py", 10 + i, visibility="private") for i in range(2)]
        page = WikiPageTemplates.render_api_reference(module=mod, public_functions=pubs + priv, config=_cfg())
        table_rows = len(re.findall(r"\| `p\d`", page.content))
        assert table_rows == 3
        assert "x0" not in page.content

    def test_api_reference_signature(self) -> None:
        mod = _mod("api", "api/")
        fn = _fn("create_user", "u.py", 5, visibility="public", signature="def create_user(id: int) -> User:")
        page = WikiPageTemplates.render_api_reference(module=mod, public_functions=[fn], config=_cfg())
        assert "create_user" in page.content
        assert "def create_user" in page.content or "signature" in page.content.lower()

    def test_api_reference_source_links(self) -> None:
        mod = _mod("api", "api/")
        fn = _fn("ping", "src/ping.py", 9, visibility="public")
        page = WikiPageTemplates.render_api_reference(module=mod, public_functions=[fn], config=_cfg())
        assert "source://" in page.content or "`src/ping.py:" in page.content


class TestRepoOverview:
    def test_repo_overview_module_index(self) -> None:
        mods = [_mod(f"m{i}", f"path/m{i}.py", f"module {i}") for i in range(5)]
        stats = {f"m{i}": {"classes": i + 1, "functions": i * 2} for i in range(5)}
        page = WikiPageTemplates.render_repo_overview(
            repository="big",
            modules=mods,
            total_pages=42,
            module_stats=stats,
            config=_cfg("big"),
        )
        assert page.page_type == PageType.REPO_OVERVIEW
        for i in range(5):
            assert f"m{i}" in page.content
        body_rows = [ln for ln in page.content.splitlines() if ln.strip().startswith("|") and "m" in ln]
        assert len([r for r in body_rows if re.search(r"m\d", r)]) >= 5

    def test_repo_overview_quick_links(self) -> None:
        page = WikiPageTemplates.render_repo_overview(
            repository="r",
            modules=[_mod("one", "one.py")],
            total_pages=3,
            module_stats={"one": {"classes": 0, "functions": 0}},
            config=_cfg("r"),
        )
        assert "architecture/overview.md" in page.content

    def test_repo_overview_has_stats(self) -> None:
        page = WikiPageTemplates.render_repo_overview(
            repository="r",
            modules=[_mod("a", "a.py")],
            total_pages=10,
            module_stats={"a": {"classes": 7, "functions": 11}},
            config=_cfg("r"),
        )
        assert "7" in page.content and "11" in page.content


class TestDetectTechStack:
    def test_detect_tech_stack_python(self) -> None:
        m = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "p", "file": "pkg/main.py", "path": "pkg"},
            uid="m1",
        )
        out = WikiPageTemplates.detect_tech_stack([m], [])
        assert "python" in out.get("languages", [])

    def test_detect_tech_stack_frameworks(self) -> None:
        fastapi = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "fastapi", "path": "site-packages/fastapi"},
        )
        importer = GraphNode(label=NodeLabel.MODULE, properties={"name": "app", "file": "app.py"})
        edge = GraphEdge(EdgeType.IMPORTS, importer.uid, fastapi.uid)
        out = WikiPageTemplates.detect_tech_stack([importer], [edge])
        assert "fastapi" in out.get("frameworks", [])


class TestNewDiagramGenerators:
    def test_layered_architecture_diagram(self) -> None:
        layers = {
            "API Layer": ["routes", "auth"],
            "Service Layer": ["core"],
        }
        d = generate_layered_architecture_diagram(layers)
        assert d.diagram_type == DiagramType.FLOWCHART
        assert d.content.startswith("graph TD")
        assert "subgraph" in d.content
        assert "routes" in d.content and "core" in d.content

    def test_module_dependency_flowchart(self) -> None:
        d = generate_module_dependency_flowchart(
            ["a", "b", "c"],
            [("a", "b"), ("b", "c")],
        )
        assert d.diagram_type == DiagramType.FLOWCHART
        assert d.content.startswith("flowchart LR")
        assert d.content.count("-->") == 2

    def test_data_flow_diagram(self) -> None:
        d = generate_data_flow_diagram(
            ["parse", "validate", "persist"],
            [("parse", "validate"), ("validate", "persist")],
        )
        assert d.diagram_type == DiagramType.FLOWCHART
        assert d.content.startswith("flowchart LR")
        for s in ("parse", "validate", "persist"):
            assert s in d.content

