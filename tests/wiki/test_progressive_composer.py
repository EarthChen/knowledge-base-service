from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.progressive_composer import ProgressiveComposer
from wiki.content_context_builder import EnrichedDomainContext, EntityDetail, MethodDetail


def test_estimate_tokens():
    pc = ProgressiveComposer(llm=None)
    assert pc.estimate_tokens("hello world") > 0
    assert pc.estimate_tokens("你好世界测试" * 100) > 200


def test_needs_progressive_short_prompt():
    pc = ProgressiveComposer(llm=None, threshold_tokens=6000)
    assert not pc.needs_progressive("Short prompt")


def test_needs_progressive_long_prompt():
    pc = ProgressiveComposer(llm=None, threshold_tokens=100)
    long_prompt = "x" * 500
    assert pc.needs_progressive(long_prompt)


def test_split_into_rounds_creates_multiple():
    pc = ProgressiveComposer(llm=None, threshold_tokens=100)
    ctx = EnrichedDomainContext(
        domain_name="Meeting",
        parent_domain="root",
        biz_entities=[
            EntityDetail(
                uid=f"u{i}",
                name=f"Svc{i}",
                repository="repo",
                file_path=f"svc{i}.java",
                entity_type="Module",
                business_summary=f"Service {i} desc",
                methods=[
                    MethodDetail(
                        name=f"method{i}",
                        signature=f"void method{i}()",
                        file_path=f"svc{i}.java",
                        start_line=10,
                        repository="repo",
                    ),
                ],
                call_chains=[],
            )
            for i in range(10)
        ],
    )
    rounds = pc.split_into_rounds("system", "long " * 500, ctx)
    assert len(rounds) >= 2
    assert all("system" in r or "user" in r for r in rounds)


@pytest.mark.asyncio
async def test_compose_progressive_merges_outputs():
    llm = AsyncMock()
    llm.return_value = '{"executive_summary": "Summary", "content": "## Section\\nContent"}'

    pc = ProgressiveComposer(llm=llm, threshold_tokens=100)
    ctx = EnrichedDomainContext(
        domain_name="Meeting",
        parent_domain="root",
        biz_entities=[
            EntityDetail(
                uid=f"u{i}",
                name=f"Svc{i}",
                repository="repo",
                file_path=f"svc{i}.java",
                entity_type="Module",
                business_summary=f"Service {i}",
                methods=[],
                call_chains=[],
            )
            for i in range(10)
        ],
    )
    summary, content = await pc.compose_progressive("system", "long " * 500, ctx)
    assert summary
    assert content
    assert llm.call_count >= 2


def test_merge_round_outputs():
    outputs = [
        "## 业务概述\nOverview content\n\n## 架构全景图\nDiagram here",
        "## 核心服务详解\nService details for Svc1\n\n## 核心服务详解\nService details for Svc2",
        "## 设计要点\nDesign notes",
    ]
    merged = ProgressiveComposer.merge_round_outputs(outputs)
    assert "业务概述" in merged
    assert "核心服务详解" in merged
    assert "设计要点" in merged
