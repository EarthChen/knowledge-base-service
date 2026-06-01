"""Sparse / empty module graph tier routing in WikiComposer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData
from wiki.models import PageType, SourceLocation, WikiConfig


def _loc(file_path: str, start: int, end: int, fqn: str, repo: str = "demo") -> SourceLocation:
    return SourceLocation(file_path=file_path, start_line=start, end_line=end, fqn=fqn, repository=repo)


def _module_node(uid: str, path: str, name: str) -> GraphNode:
    return GraphNode(label=NodeLabel.MODULE, properties={"path": path, "name": name}, uid=uid)


def _class_node(uid: str, name: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS,
        properties={"name": name, "file": f"{name}.java", "fqn": f"p.{name}"},
        uid=uid,
    )


def _edge(et: EdgeType, src: str, tgt: str) -> GraphEdge:
    return GraphEdge(edge_type=et, source_uid=src, target_uid=tgt, properties={})


def _module_page_data(
    *,
    children: list[GraphNode] | None = None,
    edges: list[GraphEdge] | None = None,
    methods: list[GraphNode] | None = None,
    business_summary: str | None = None,
) -> PageData:
    mod = _module_node("mod:empty", "empty/", "empty_mod")
    return PageData(
        node=mod,
        edges=edges or [],
        children=children or [],
        source_location=_loc("empty/__init__.py", 1, 1, "empty_mod"),
        method_locations=[],
        business_summary=business_summary,
        methods=methods or [],
    )


def _composer_with_llm() -> tuple[WikiComposer, AsyncMock]:
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="LLM tier-2 overview body.")
    composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder())
    return composer, llm


@pytest.mark.asyncio
async def test_empty_graph_forced_tier3() -> None:
    composer, llm = _composer_with_llm()
    cfg = WikiConfig(repository="demo", mode="full", language="en")
    page = await composer.compose_page(
        _module_page_data(children=[], edges=[], methods=[]),
        PageType.MODULE_OVERVIEW,
        cfg,
    )

    assert page is not None
    assert page.metadata.fallback_tier == 3
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_sparse_graph_forced_tier1() -> None:
    composer, llm = _composer_with_llm()
    cfg = WikiConfig(repository="demo", mode="full", language="en")
    children = [_class_node(f"class:C{i}", f"C{i}") for i in range(3)]
    page = await composer.compose_page(
        _module_page_data(children=children, business_summary="Sparse module summary text."),
        PageType.MODULE_OVERVIEW,
        cfg,
    )

    assert page is not None
    assert page.metadata.fallback_tier == 1
    assert "Sparse module summary text." in page.content
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_graph_uses_tier2() -> None:
    composer, llm = _composer_with_llm()
    cfg = WikiConfig(repository="demo", mode="full", language="en")
    children = [_class_node(f"class:C{i}", f"C{i}") for i in range(10)]
    page = await composer.compose_page(
        _module_page_data(children=children),
        PageType.MODULE_OVERVIEW,
        cfg,
    )

    assert page is not None
    assert page.metadata.fallback_tier == 2
    assert "LLM tier-2 overview body." in page.content
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_sparse_module_chinese_h2() -> None:
    composer, _llm = _composer_with_llm()
    cfg = WikiConfig(repository="demo", mode="full", language="en")
    page = await composer.compose_page(
        _module_page_data(children=[], edges=[], methods=[]),
        PageType.MODULE_OVERVIEW,
        cfg,
    )

    assert page is not None
    assert "## 概述" in page.content
    assert "## Overview" not in page.content


@pytest.mark.asyncio
async def test_sparse_module_no_empty_sections() -> None:
    composer, _llm = _composer_with_llm()
    cfg = WikiConfig(repository="demo", mode="full", language="en")
    page = await composer.compose_page(
        _module_page_data(children=[], edges=[], methods=[]),
        PageType.MODULE_OVERVIEW,
        cfg,
    )

    assert page is not None
    assert "Key components" not in page.content
    assert "No nested graph children" not in page.content


@pytest.mark.asyncio
async def test_non_module_type_unaffected() -> None:
    composer, llm = _composer_with_llm()
    cls = GraphNode(
        label=NodeLabel.CLASS,
        properties={"name": "Svc", "file": "Svc.java", "fqn": "p.Svc"},
        uid="class:Svc.java:Svc:1",
    )
    pd = PageData(
        node=cls,
        edges=[],
        children=[],
        source_location=_loc("Svc.java", 1, 50, "p.Svc"),
        method_locations=[],
        business_summary=None,
        methods=[],
    )
    cfg = WikiConfig(repository="demo", mode="full", language="en")
    page = await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)

    assert page is not None
    assert page.metadata.fallback_tier == 2
    llm.generate.assert_awaited_once()

    domain_node = GraphNode(
        label=NodeLabel.MODULE,
        properties={"name": "billing", "path": "billing/"},
        uid="mod:billing",
    )
    domain_pd = PageData(
        node=domain_node,
        edges=[],
        children=[],
        source_location=_loc("billing/__init__.py", 1, 1, "billing"),
        method_locations=[],
        business_summary=None,
        methods=[],
    )
    llm.reset_mock()
    domain_page = await composer.compose_page(domain_pd, PageType.DOMAIN_OVERVIEW, cfg)
    assert domain_page is not None
    assert domain_page.metadata.fallback_tier == 2
    assert llm.generate.await_count >= 1
