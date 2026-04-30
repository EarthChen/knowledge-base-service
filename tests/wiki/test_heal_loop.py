"""Tests for wiki pipeline heal loop (quality_gate <-> heal_pages) without page bloat."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wiki.pipeline_graph import build_wiki_pipeline

_HEAL_GOOD_MARKDOWN = (
    "## Overview\nDetailed description of the business domain and responsibilities.\n\n"
    "## Key components\n- CoreService — handles primary workflows\n- Helper — utility operations\n\n"
    "## Relationships\n- Depends on downstream APIs; invoked by upstream controllers.\n\n"
    "```mermaid\nsequenceDiagram\nA->>B: process\n```\n\n"
    "## 业务概述\nDetailed Chinese summary of the business domain.\n\n"
    "## 核心业务流程\nOperational flow description.\n\n"
    "## 核心服务详情\n### Service\nHandles core business logic with multiple APIs.\n\n"
    "## 关联主题\n- [[other-domain]]\n"
)


@pytest.mark.asyncio
async def test_heal_loop_does_not_duplicate_pages() -> None:
    """After heal cycle, each page path appears exactly once in ``pages``."""
    mock_llm = AsyncMock()
    call_count: dict[str, int] = {"n": 0}

    async def mock_generate(prompt: str, system: str = "", **kwargs: object) -> str:
        call_count["n"] += 1
        if "Improve this wiki page" in prompt:
            return _HEAL_GOOD_MARKDOWN
        if call_count["n"] <= 5:
            return "# Short\nBrief."
        return _HEAL_GOOD_MARKDOWN

    mock_llm.generate = AsyncMock(side_effect=mock_generate)

    pipeline = build_wiki_pipeline()
    initial_state = {
        "business_id": "heal-test",
        "repositories": ["repo"],
        "config": {},
        "modules": {
            "repo": [
                {
                    "uid": "Module::Svc:0",
                    "label": "Module",
                    "properties": {
                        "name": "Svc",
                        "annotations": ["@Service"],
                        "methods_count": 10,
                        "start_line": 0,
                        "end_line": 300,
                        "semantic_roles": ["service"],
                        "business_summary": "Core service",
                        "methods": ["doWork"],
                    },
                },
            ],
        },
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
        "entity_roles": {},
        "role_stats": {},
        "is_incremental": False,
        "reorg_type": "",
        "affected_domains": [],
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
    }

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "heal-test-1", "llm": mock_llm}},
    )

    paths = [p.get("path", "") for p in result.get("pages", [])]
    unique_paths = set(paths)
    for path in unique_paths:
        if not path:
            continue
        count = paths.count(path)
        assert count == 1, f"Page '{path}' appears {count} times (should be 1)"
