"""Unit tests for wiki.composer — T1.4 WikiComposer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData
from wiki.models import DiagramType, PageType, WikiConfig
from wiki.models import SourceLocation


def _loc(file_path: str, start: int, end: int, fqn: str, repo: str = "demo") -> SourceLocation:
    return SourceLocation(file_path=file_path, start_line=start, end_line=end, fqn=fqn, repository=repo)


def _module_node(uid: str, path: str, name: str) -> GraphNode:
    return GraphNode(label=NodeLabel.MODULE, properties={"path": path, "name": name}, uid=uid)


def _class_node(uid: str, name: str, file_path: str, start: int, end: int, fqn: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS,
        properties={
            "name": name,
            "file": file_path,
            "start_line": start,
            "end_line": end,
            "fqn": fqn,
        },
        uid=uid,
    )


def _fn(uid: str, name: str, line: int, file_path: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.FUNCTION,
        properties={
            "name": name,
            "file": file_path,
            "start_line": line,
            "end_line": line + 3,
            "fqn": f"x.{name}",
        },
        uid=uid,
    )


def _edge(et: EdgeType, src: str, tgt: str) -> GraphEdge:
    return GraphEdge(edge_type=et, source_uid=src, target_uid=tgt, properties={})


class TestFallbackTiers:
    async def test_fallback_tier1_summary_exists(self) -> None:
        cls = _class_node("class:UserService.java:UserService:10", "UserService", "src/UserService.java", 10, 200, "u.User")
        summ = "Tier-1 authoritative summary."
        llm = AsyncMock()
        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/UserService.java", 10, 200, "u.User"),
            method_locations=[],
            business_summary=summ,
            methods=[],
        )
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        assert summ in page.content
        assert page.metadata.fallback_tier == 1
        llm.generate.assert_not_called()

    async def test_fallback_tier2_llm_available(self) -> None:
        cls = _class_node("class:A.java:A:1", "A", "src/A.java", 1, 50, "p.A")
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="LLM-written overview body.")

        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/A.java", 1, 50, "p.A"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="full")
        page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        assert "LLM-written overview body." in page.content or "LLM-written" in page.content
        assert page.metadata.fallback_tier == 2
        llm.generate.assert_called()

    async def test_fallback_tier3_structural(self) -> None:
        cls = _class_node("class:A.java:A:1", "A", "src/A.java", 1, 50, "p.A")
        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/A.java", 1, 50, "p.A"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="full")
        page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        assert page.metadata.fallback_tier == 3
        assert "A" in page.content
        assert "## Overview" in page.content


class TestPageTypes:
    async def test_module_overview_page(self) -> None:
        mod = _module_node("mod:svc", "service/", "service")
        c1 = _class_node("class:c1", "OrderSvc", "svc/O.java", 1, 10, "OrderSvc")
        edges = [_edge(EdgeType.IMPORTS, mod.uid, "mod:other")]
        pd = PageData(
            node=mod,
            edges=edges,
            children=[c1],
            source_location=_loc("service/__init__.py", 1, 1, "service"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        assert page.title == "service" or "service" in page.title
        assert "OrderSvc" in page.content
        assert any(d.diagram_type == DiagramType.DEPENDENCY_GRAPH for d in page.diagrams)

    async def test_class_detail_page(self) -> None:
        cls = _class_node("class:U.java:UserService:10", "UserService", "src/U.java", 10, 99, "p.UserService")
        base = _class_node("class:B.java:Base:1", "BaseService", "src/B.java", 1, 5, "p.Base")
        m1 = _fn("fn1", "createUser", 20, "src/U.java")
        edges = [
            _edge(EdgeType.INHERITS, cls.uid, base.uid),
            _edge(EdgeType.CONTAINS, cls.uid, m1.uid),
        ]
        pd = PageData(
            node=cls,
            edges=edges,
            children=[m1],
            source_location=_loc("src/U.java", 10, 99, "p.UserService"),
            method_locations=[_loc("src/U.java", 20, 23, "p.UserService.createUser")],
            business_summary=None,
            methods=[m1],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        assert "UserService" in page.content
        assert "createUser" in page.content
        assert any(d.diagram_type == DiagramType.CLASS_DIAGRAM for d in page.diagrams)


class TestContextInjection:
    async def test_compose_with_glossary(self) -> None:
        cls = _class_node("class:X.java:X:1", "X", "src/X.java", 1, 10, "p.X")
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="Body")

        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/X.java", 1, 10, "p.X"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="full")
        glossary = {"KBS": "Knowledge-Base-Service"}
        await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg, glossary=glossary)
        call_kw = llm.generate.call_args
        prompt = call_kw[0][0] if call_kw[0] else ""
        assert "KBS" in prompt and "Knowledge-Base-Service" in prompt

    async def test_compose_with_parent_summary(self) -> None:
        cls = _class_node("class:X.java:X:1", "X", "src/X.java", 1, 10, "p.X")
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="Body")

        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/X.java", 1, 10, "p.X"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="full")
        await composer.compose_page(
            pd,
            PageType.CLASS_DETAIL,
            cfg,
            parent_context="Upstream module handles routing.",
        )
        prompt = llm.generate.call_args[0][0]
        assert "Upstream module handles routing." in prompt


class TestModes:
    async def test_compose_structure_mode(self) -> None:
        cls = _class_node("class:X.java:X:1", "X", "src/X.java", 1, 10, "p.X")
        llm = AsyncMock()
        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/X.java", 1, 10, "p.X"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        llm.generate.assert_not_called()

    async def test_compose_full_mode(self) -> None:
        cls = _class_node("class:X.java:X:1", "X", "src/X.java", 1, 10, "p.X")
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="Synthetic")

        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/X.java", 1, 10, "p.X"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="full")
        await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        llm.generate.assert_called()


class TestTier3Templates:
    async def test_tier3_natural_language_template_module(self) -> None:
        mod = _module_node("mod:api", "api/", "api")
        pd = PageData(
            node=mod,
            edges=[_edge(EdgeType.IMPORTS, mod.uid, "mod:core")],
            children=[],
            source_location=_loc("api/__init__.py", 1, 1, "api"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        text = page.content.lower()
        assert "module" in text or "api" in text

    async def test_tier3_natural_language_template_class(self) -> None:
        child = _class_node("class:C.java:Child:5", "Child", "src/C.java", 5, 20, "p.Child")
        parent = _class_node("class:P.java:Parent:1", "Parent", "src/P.java", 1, 4, "p.Parent")
        edges = [_edge(EdgeType.INHERITS, child.uid, parent.uid)]
        pd = PageData(
            node=child,
            edges=edges,
            children=[],
            source_location=_loc("src/C.java", 5, 20, "p.Child"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        assert "inherits" in page.content.lower() or "extends" in page.content.lower()
        assert "Parent" in page.content

    async def test_tier3_includes_relationship_info(self) -> None:
        ctrl = _class_node("class:Ctl.java:UserController:1", "UserController", "src/Ctl.java", 1, 40, "p.C")
        svc = _class_node("class:S.java:UserService:1", "UserService", "src/S.java", 1, 30, "p.S")
        edges = [_edge(EdgeType.CALLS, ctrl.uid, svc.uid)]
        pd = PageData(
            node=ctrl,
            edges=edges,
            children=[],
            source_location=_loc("src/Ctl.java", 1, 40, "p.C"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        rel = page.content.lower()
        assert "usercontroller" in rel or "controller" in rel
        assert "call" in rel or "depends" in rel or "uses" in rel


class TestComposerCoverageGaps:
    """Hit _primary_name fallbacks, tier-2 entity digest, and zh tier-3 branches."""

    async def test_primary_name_uses_path_segment_when_name_missing(self) -> None:
        mod = GraphNode(
            label=NodeLabel.MODULE,
            uid="mod:onlypath",
            properties={"path": "src/deep/pkg/widget"},
        )
        pd = PageData(
            node=mod,
            edges=[],
            children=[],
            source_location=_loc("src/deep/pkg/widget/__init__.py", 1, 1, "widget"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        assert "widget" in page.title

    async def test_tier2_entity_digest_includes_module_path_and_child_counts(self) -> None:
        mod = GraphNode(
            label=NodeLabel.MODULE,
            uid="mod:api",
            properties={"name": "api", "path": "projects/api"},
        )
        child = _class_node("class:C.java:C:1", "C", "f.java", 1, 2, "p.C")
        pd = PageData(
            node=mod,
            edges=[_edge(EdgeType.IMPORTS, mod.uid, "mod:dep")],
            children=[child],
            source_location=_loc("api/__init__.py", 1, 1, "api"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="Overview body.")
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="full")
        await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        prompt = llm.generate.call_args[0][0]
        assert "- Path: projects/api" in prompt
        assert "Child classes/modules: 1" in prompt

    async def test_tier2_entity_digest_class_includes_fqn_and_methods_count(self) -> None:
        cls = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "Thing",
                "fqn": "pkg.Thing",
                "file": "src/T.java",
                "start_line": 1,
                "end_line": 50,
            },
            uid="class:T.java:Thing:1",
        )
        m1 = _fn("fn1", "run", 5, "src/T.java")
        pd = PageData(
            node=cls,
            edges=[],
            children=[],
            source_location=_loc("src/T.java", 1, 50, "pkg.Thing"),
            method_locations=[],
            business_summary=None,
            methods=[m1],
        )
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="Body.")
        composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="full")
        await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        prompt = llm.generate.call_args[0][0]
        assert "- FQN: pkg.Thing" in prompt
        assert "Methods: 1" in prompt

    async def test_tier3_zh_module_template(self) -> None:
        mod = _module_node("mod:zh", "svc/", "svc")
        fn = _fn("fn1", "helper", 2, "svc/h.py")
        pd = PageData(
            node=mod,
            edges=[],
            children=[fn],
            source_location=_loc("svc/__init__.py", 1, 1, "svc"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure", language="zh")
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        assert "模块" in page.content

    async def test_tier3_zh_class_multiple_parents_and_many_methods(self) -> None:
        cls = _class_node("class:A.java:A:1", "A", "src/A.java", 1, 50, "p.A")
        base1 = _class_node("class:B1.java:B1:1", "B1", "src/B1.java", 1, 4, "p.B1")
        base2 = _class_node("class:B2.java:B2:1", "B2", "src/B2.java", 1, 4, "p.B2")
        edges = [
            _edge(EdgeType.INHERITS, cls.uid, base1.uid),
            _edge(EdgeType.INHERITS, cls.uid, base2.uid),
        ]
        methods = [_fn(f"fn{i}", f"m{i}", 10 + i, "src/A.java") for i in range(6)]
        pd = PageData(
            node=cls,
            edges=edges,
            children=[],
            source_location=_loc("src/A.java", 1, 50, "p.A"),
            method_locations=[],
            business_summary=None,
            methods=methods,
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure", language="zh")
        page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        body = page.content
        assert "继承" in body or "父类型" in body
        assert "另有" in body or "方法" in body

    async def test_tier3_en_module_truncates_many_classes(self) -> None:
        mod = _module_node("mod:many", "bulk/", "bulk")
        classes = [
            _class_node(f"class:C{i}.java:C{i}:1", f"C{i}", f"f{i}.java", 1, 2, f"p.C{i}") for i in range(10)
        ]
        pd = PageData(
            node=mod,
            edges=[],
            children=classes,
            source_location=_loc("bulk/__init__.py", 1, 1, "bulk"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        assert "+2 more" in page.content or "+1 more" in page.content

