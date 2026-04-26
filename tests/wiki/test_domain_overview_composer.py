"""Tests for DomainOverviewComposer — cross-repo business domain overview pages."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.domain_overview_composer import DomainOverviewComposer
from wiki.models import EnrichmentLevel, PageType


def _mod(repo: str, name: str, **props: str) -> GraphNode:
    merged = {"name": name, "repository": repo, **props}
    return GraphNode(label=NodeLabel.MODULE, properties=merged, uid=f"mod:{repo}:{name}")


@pytest.mark.asyncio
async def test_compose_with_llm() -> None:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=(
            "## Business purpose\n"
            "This domain orchestrates billing and invoicing.\n\n"
            "## Key modules\n"
            "- **billing-api**: HTTP surface\n"
            "- **billing-core**: rules engine\n\n"
            "## Collaboration\n"
            "API delegates to core.\n\n"
            "```mermaid\nflowchart LR\n  API --> CORE\n```\n"
        ),
    )
    composer = DomainOverviewComposer(llm=llm)
    modules = [
        ("repo-a", "billing-api", _mod("repo-a", "billing-api", business_summary="HTTP layer")),
        ("repo-b", "billing-core", _mod("repo-b", "billing-core", docstring="Core rules")),
    ]
    page = await composer.compose("billing", modules, language="en")

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert page.path == "/billing/_overview"
    assert "orchestrates billing" in page.content
    llm.generate.assert_awaited()
    assert page.metadata.generation_mode == "business"
    assert page.metadata.enrichment_level == EnrichmentLevel.BASE
    assert len(page.diagrams) >= 1
    assert "flowchart" in page.diagrams[0].content.lower()


@pytest.mark.asyncio
async def test_compose_without_llm() -> None:
    composer = DomainOverviewComposer(llm=None)
    modules = [
        ("alpha", "svc", _mod("alpha", "svc", business_summary="Alpha service")),
    ]
    page = await composer.compose("dom", modules, language="en")

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert page.path == "/dom/_overview"
    assert "alpha" in page.content.lower()
    assert "svc" in page.content
    assert "Alpha service" in page.content
    assert page.metadata.generation_mode == "business"
    assert page.metadata.enrichment_level == EnrichmentLevel.BASE


@pytest.mark.asyncio
async def test_compose_includes_all_repos() -> None:
    composer = DomainOverviewComposer(llm=None)
    modules = [
        ("repo-one", "m1", _mod("repo-one", "m1")),
        ("repo-two", "m2", _mod("repo-two", "m2")),
        ("repo-three", "m3", _mod("repo-three", "m3")),
    ]
    page = await composer.compose("multi", modules, language="en")

    for repo in ("repo-one", "repo-two", "repo-three"):
        assert repo in page.content


@pytest.mark.asyncio
async def test_compose_empty_modules() -> None:
    composer = DomainOverviewComposer(llm=None)
    page = await composer.compose("empty-domain", [], language="en")

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert page.path == "/empty-domain/_overview"
    assert page.content
    assert page.metadata.node_count == 0
    assert page.metadata.generation_mode == "business"


@pytest.mark.asyncio
async def test_compose_zh_language() -> None:
    composer = DomainOverviewComposer(llm=None)
    modules = [
        ("alpha", "svc", _mod("alpha", "svc", business_summary="服务说明")),
    ]
    page = await composer.compose("订单域", modules, language="zh")

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert "# 业务域：订单域" in page.content
    assert "## 仓库与模块" in page.content
    assert "### 仓库 `alpha`" in page.content
    assert "服务说明" in page.content


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_llm_output", ["", "   ", "\n\t  \n"])
async def test_compose_llm_empty_response_degrades(empty_llm_output: str) -> None:
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=empty_llm_output)

    composer = DomainOverviewComposer(llm=llm)
    modules = [
        ("repo-a", "billing-api", _mod("repo-a", "billing-api", business_summary="HTTP layer")),
        ("repo-b", "billing-core", _mod("repo-b", "billing-core", docstring="Core rules")),
    ]
    page = await composer.compose("billing", modules, language="en")

    assert "## Repositories and modules" in page.content
    assert "### Repository `repo-a`" in page.content
    assert "### Repository `repo-b`" in page.content
    assert "billing-api" in page.content
    assert "HTTP layer" in page.content
    assert page.diagrams == []


@pytest.mark.asyncio
async def test_compose_llm_missing_repo_appends() -> None:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=(
            "## Business purpose\n"
            "Billing domain.\n\n"
            "## Key modules\n"
            "Only mentions repo-a.\n"
            "- **billing-api** in `repo-a`\n"
        ),
    )
    composer = DomainOverviewComposer(llm=llm)
    modules = [
        ("repo-a", "billing-api", _mod("repo-a", "billing-api")),
        ("repo-b", "billing-core", _mod("repo-b", "billing-core")),
    ]
    page = await composer.compose("billing", modules, language="en")

    assert "repo-a" in page.content
    assert "repo-b" in page.content
    assert "## Repositories" in page.content
    assert "`repo-b`" in page.content


@pytest.mark.asyncio
async def test_compose_llm_failure_degrades() -> None:
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    composer = DomainOverviewComposer(llm=llm)
    modules = [
        ("r1", "mod-a", _mod("r1", "mod-a", business_summary="Summary A")),
    ]
    page = await composer.compose("degraded", modules, language="en")

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert "r1" in page.content
    assert "mod-a" in page.content
    assert "Summary A" in page.content
    assert page.diagrams == []
