"""Tests for TopicPageComposer.compose_leaf_domain_from_context (unified prompts, Template B)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wiki.content_context_builder import CallChainStep, EntityDetail, EnrichedDomainContext, MethodDetail


@pytest.mark.asyncio
async def test_compose_from_context_single_page() -> None:
    from wiki.topic_page_composer import TopicPageComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value=json.dumps(
            {
                "executive_summary": "会议发起子域处理信令封装",
                "content": (
                    "## 业务概述\n会议发起...\n\n## 核心业务流程\n```mermaid\nsequenceDiagram\nA->>B: call\n```\n\n"
                    "## 核心服务详解\n### MeetingSendBH\n处理信令...\n\n## 设计要点与注意事项\n关键逻辑..."
                ),
            },
            ensure_ascii=False,
        ),
    )

    context = EnrichedDomainContext(
        domain_name="Meeting Initiation",
        parent_domain="Meeting",
        biz_entities=[
            EntityDetail(
                uid="u1",
                name="MeetingSendBH",
                repository="ultron",
                file_path="MeetingSendBH.java",
                entity_type="Module",
                business_summary="Handle meeting send signals",
                methods=[
                    MethodDetail(
                        name="handleSend",
                        signature="void handleSend(Request req)",
                        file_path="MeetingSendBH.java",
                        start_line=45,
                        repository="ultron",
                    ),
                ],
                call_chains=[
                    CallChainStep(
                        caller="MeetingSendBH",
                        callee="MeetingService",
                        caller_method="handleSend",
                        callee_method="create",
                        relationship="CALLS",
                    ),
                ],
            ),
        ],
        intra_domain_calls=[
            CallChainStep(
                caller="MeetingSendBH",
                callee="MeetingService",
                caller_method="handleSend",
                callee_method="create",
                relationship="CALLS",
            ),
        ],
        dependent_domains=["User Management"],
    )

    composer = TopicPageComposer(llm=mock_llm, token_budget=8000)
    pages = await composer.compose_leaf_domain_from_context(context)

    assert len(pages) >= 1
    assert pages[0]["page_type"] == "topic"
    assert pages[0]["metadata"]["executive_summary"] == "会议发起子域处理信令封装"
    assert "业务概述" in pages[0]["content"]


@pytest.mark.asyncio
async def test_compose_from_context_uses_unified_prompt() -> None:
    from wiki.topic_page_composer import TopicPageComposer
    from wiki.unified_prompt_templates import UNIFIED_WIKI_SYSTEM_PROMPT

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"executive_summary": "s", "content": "## 业务概述\nc"}',
    )

    context = EnrichedDomainContext(
        domain_name="test",
        parent_domain="root",
        biz_entities=[
            EntityDetail(
                uid="u1",
                name="Svc",
                repository="r",
                file_path="f.java",
                entity_type="Module",
                business_summary="d",
                methods=[],
                call_chains=[],
            ),
        ],
    )

    composer = TopicPageComposer(llm=mock_llm, token_budget=8000)
    await composer.compose_leaf_domain_from_context(context)

    call_args = mock_llm.generate.call_args
    system_used = call_args.kwargs.get("system", "")
    assert system_used == UNIFIED_WIKI_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_compose_from_context_with_overview_delegation() -> None:
    from wiki.domain_overview_composer import DomainOverviewComposer
    from wiki.topic_page_composer import TopicPageComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"executive_summary": "sub", "content": "## 业务概述\nSub page content"}',
    )

    entities = [
        EntityDetail(
            uid=f"u{i}",
            name=f"Svc{i}",
            repository="r",
            file_path=f"svc{i}.java",
            entity_type="Module",
            business_summary=f"Service {i}",
            methods=[],
            call_chains=[],
        )
        for i in range(10)
    ]

    context = EnrichedDomainContext(
        domain_name="large-domain",
        parent_domain="root",
        biz_entities=entities,
    )

    overview_composer = DomainOverviewComposer(llm=mock_llm)

    composer = TopicPageComposer(llm=mock_llm, token_budget=8000)
    pages = await composer.compose_leaf_domain_from_context(
        context,
        overview_composer=overview_composer,
    )

    assert len(pages) >= 1
    page_types = [p["page_type"] for p in pages]
    assert "topic" in page_types or "domain_overview" in page_types


@pytest.mark.asyncio
async def test_compose_from_context_llm_failure() -> None:
    from wiki.topic_page_composer import TopicPageComposer

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM error"))

    context = EnrichedDomainContext(
        domain_name="failing",
        parent_domain="root",
        biz_entities=[
            EntityDetail(
                uid="u1",
                name="Svc",
                repository="r",
                file_path="f.java",
                entity_type="Module",
                business_summary="d",
                methods=[],
                call_chains=[],
            ),
        ],
    )

    composer = TopicPageComposer(llm=mock_llm, token_budget=8000)
    pages = await composer.compose_leaf_domain_from_context(context)

    assert isinstance(pages, list)
