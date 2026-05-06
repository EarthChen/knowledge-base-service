import json
import pytest
from unittest.mock import AsyncMock

from wiki.content_context_builder import EnrichedDomainContext, EntityDetail
from wiki.models import EnrichmentLevel, PageType


@pytest.mark.asyncio
async def test_compose_from_context_returns_wiki_page():
    from wiki.domain_overview_composer import DomainOverviewComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value=json.dumps(
            {
                "executive_summary": "会议管理域负责会议信令的处理",
                "content": "## 业务概述\n会议管理域...\n\n## 架构全景图\n```mermaid\nflowchart TD\nA-->B\n```\n\n## 子主题导航\n- 发起流程\n\n## 关键入口\n- MeetingSendBH\n\n## 跨域依赖与交互\n- 依赖用户管理",
            },
            ensure_ascii=False,
        ),
    )

    context = EnrichedDomainContext(
        domain_name="meeting",
        parent_domain="root",
        biz_entities=[
            EntityDetail(
                uid="u1",
                name="MeetingSendBH",
                repository="ultron",
                file_path="f.java",
                entity_type="Module",
                business_summary="Send meetings",
                methods=[],
                call_chains=[],
            ),
        ],
        sibling_domains=["live"],
        dependent_domains=["user-management"],
        sub_topics=[{"title": "Meeting Initiation", "description": "发起", "entity_count": 3}],
    )

    composer = DomainOverviewComposer(llm=mock_llm)
    page = await composer.compose_from_context(context, language="zh")

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert page.metadata.executive_summary == "会议管理域负责会议信令的处理"
    assert "业务概述" in page.content
    assert len(page.diagrams) >= 1
    assert page.metadata.enrichment_level == EnrichmentLevel.FULL


@pytest.mark.asyncio
async def test_compose_from_context_uses_unified_prompt():
    from wiki.domain_overview_composer import DomainOverviewComposer
    from wiki.unified_prompt_templates import UNIFIED_WIKI_SYSTEM_PROMPT

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"executive_summary": "s", "content": "## 业务概述\nc"}')

    context = EnrichedDomainContext(domain_name="test", parent_domain="root")
    composer = DomainOverviewComposer(llm=mock_llm)
    await composer.compose_from_context(context)

    call_args = mock_llm.generate.call_args
    system_used = call_args.kwargs.get("system", "")
    assert system_used == UNIFIED_WIKI_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_compose_from_context_llm_failure_fallback():
    from wiki.domain_overview_composer import DomainOverviewComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))

    context = EnrichedDomainContext(
        domain_name="meeting",
        parent_domain="root",
        biz_entities=[
            EntityDetail(
                uid="u1",
                name="Svc",
                repository="r",
                file_path="f.java",
                entity_type="Module",
                business_summary="desc",
                methods=[],
                call_chains=[],
            ),
        ],
    )
    composer = DomainOverviewComposer(llm=mock_llm)
    page = await composer.compose_from_context(context)

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert page.content
    assert page.metadata.enrichment_level == EnrichmentLevel.FULL


@pytest.mark.asyncio
async def test_compose_from_context_no_llm():
    from wiki.domain_overview_composer import DomainOverviewComposer

    context = EnrichedDomainContext(domain_name="test", parent_domain="root")
    composer = DomainOverviewComposer(llm=None)
    page = await composer.compose_from_context(context)

    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert "test" in page.title
    assert page.metadata.enrichment_level == EnrichmentLevel.FULL
