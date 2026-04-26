"""Multi-language (zh/en) wiki pipeline — T-S4."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData
from wiki.models import PageType, SourceLocation, WikiConfig, WikiStructure, WikiStructureNode
from wiki.service import WikiService


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


def _edge(et: EdgeType, src: str, tgt: str) -> GraphEdge:
    return GraphEdge(edge_type=et, source_uid=src, target_uid=tgt, properties={})


class TestWikiConfigLanguage:
    def test_wiki_config_default_language(self) -> None:
        cfg = WikiConfig(repository="r")
        assert cfg.language == "en"

    def test_wiki_config_zh_language(self) -> None:
        cfg = WikiConfig(repository="r", language="zh")
        assert cfg.language == "zh"

    def test_wiki_config_invalid_language(self) -> None:
        with pytest.raises(ValueError, match="language"):
            WikiConfig(repository="r", language="xx")


class TestTier3Templates:
    @pytest.mark.asyncio
    async def test_tier3_template_en(self) -> None:
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
        cfg = WikiConfig(repository="demo", mode="structure", language="en")
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        lower = page.content.lower()
        assert "module" in lower or "organizes" in lower or "codebase" in lower

    @pytest.mark.asyncio
    async def test_tier3_template_zh(self) -> None:
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
        cfg = WikiConfig(repository="demo", mode="structure", language="zh")
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        assert re.search(r"[\u4e00-\u9fff]", page.content)

    @pytest.mark.asyncio
    async def test_tier3_template_fallback(self) -> None:
        """Unknown language string falls back to English templates (composer-side)."""
        mod = _module_node("mod:api", "api/", "api")
        pd = PageData(
            node=mod,
            edges=[],
            children=[],
            source_location=_loc("api/__init__.py", 1, 1, "api"),
            method_locations=[],
            business_summary=None,
            methods=[],
        )
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        cfg = WikiConfig(repository="demo", mode="structure")
        cfg.language = "bogus"  # bypass __post_init__ validation to exercise composer fallback
        page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, cfg)
        lower = page.content.lower()
        assert "module" in lower or "organizes" in lower or "codebase" in lower


class TestLLMPromptLanguage:
    @pytest.mark.asyncio
    async def test_llm_prompt_includes_language_en(self) -> None:
        cls = _class_node("class:X.java:X:1", "X", "src/X.java", 1, 10, "p.X")
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="Overview body.")
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
        cfg = WikiConfig(repository="demo", mode="full", language="en")
        await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        prompt = llm.generate.call_args[0][0]
        assert "English" in prompt

    @pytest.mark.asyncio
    async def test_llm_prompt_includes_language_zh(self) -> None:
        cls = _class_node("class:X.java:X:1", "X", "src/X.java", 1, 10, "p.X")
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="概述正文。")
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
        cfg = WikiConfig(repository="demo", mode="full", language="zh")
        await composer.compose_page(pd, PageType.CLASS_DETAIL, cfg)
        prompt = llm.generate.call_args[0][0]
        assert "中文" in prompt


class TestStyleSheetAndGlossaryHeaders:
    def test_style_sheet_language_en(self) -> None:
        sheet = WikiContextBuilder().build_style_sheet("en")
        assert "Tone" in sheet or "tone" in sheet.lower()

    def test_style_sheet_language_zh(self) -> None:
        sheet = WikiContextBuilder().build_style_sheet("zh")
        assert re.search(r"[\u4e00-\u9fff]", sheet)

    def test_glossary_header_zh(self) -> None:
        b = WikiContextBuilder()
        style = b.build_style_sheet("zh")
        ctx = b.build_page_context("", {"K": "V"}, style, language="zh")
        assert "术语" in ctx or "词汇" in ctx


class TestServiceLanguagePropagation:
    @pytest.mark.asyncio
    async def test_service_passes_language(self) -> None:
        structure = WikiStructure(
            repository="r",
            root=WikiStructureNode(
                path="README.md",
                title="R",
                page_type=PageType.REPO_OVERVIEW,
                children=[],
            ),
            total_pages=1,
        )
        captured: dict[str, WikiConfig] = {}

        async def fake_compose_all(
            repository: str,
            struct: WikiStructure,
            config: WikiConfig,
            _composer: object,
            _importance_tiers: object = None,
            _llm_provider: str | None = None,
        ) -> tuple[list, bool]:
            captured["config"] = config
            return [], False

        svc = WikiService(graph=AsyncMock(), llm=None, repository_exists=AsyncMock(return_value=True))
        svc._planner.plan = AsyncMock(return_value=structure)
        svc._compose_all_pages = fake_compose_all  # type: ignore[method-assign]

        await svc.generate("r", "repo", "structure", "json", language="zh")
        assert captured["config"].language == "zh"
