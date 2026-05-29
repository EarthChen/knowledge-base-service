from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.agents.context_compactor import CompactionResult, ExploreCompactor


@pytest.mark.asyncio
async def test_compact_returns_structured_result():
    llm = MagicMock()
    llm_response = (
        "## 1. Primary Objective\nExplore module A\n"
        "## 2. Key Discoveries\n- ClassA (path/a.py): main entry\n"
        "## 3. Call Chains & Dependencies\n- A → B → C\n"
        "## 4. Reasoning Chain\n- Found X so Y\n"
        "## 5. Variables & State\n- config | true | flag\n"
        "## 6. Completed Steps\n- Read A\n"
        "## 7. Pending Actions\n- Read B\n"
        "## 8. Errors & Solutions\n- None\n"
        "## 9. Next Action\n- Continue"
    )
    llm.complete = AsyncMock(return_value=llm_response)

    compactor = ExploreCompactor(llm_port=llm)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "thinking"},
        {"role": "tool", "content": "result " * 500},
    ]
    result = await compactor.compact(msgs, 1, 3)
    assert isinstance(result, CompactionResult)
    assert len(result.summary) > 0
    assert len(result.key_findings) > 0
    assert result.compressed_chars < result.original_chars


@pytest.mark.asyncio
async def test_compact_extracts_call_chains():
    llm = MagicMock()
    llm_response = (
        "## 1. Primary Objective\nGoal\n"
        "## 2. Key Discoveries\n- Entity (path): desc\n"
        "## 3. Call Chains & Dependencies\n- A → B → C: flow\n- D → E: data\n"
        "## 4. Reasoning Chain\n- X\n"
        "## 5. Variables & State\n- v\n"
        "## 6. Completed Steps\n- s\n"
        "## 7. Pending Actions\n- p\n"
        "## 8. Errors & Solutions\n- e\n"
        "## 9. Next Action\n- n"
    )
    llm.complete = AsyncMock(return_value=llm_response)

    compactor = ExploreCompactor(llm_port=llm)
    msgs = [{"role": "system", "content": "s"}, {"role": "assistant", "content": "t"}]
    result = await compactor.compact(msgs, 1, 2)
    assert len(result.call_chains) >= 1


def test_format_history_truncates_at_30k():
    compactor = ExploreCompactor(llm_port=MagicMock())
    msgs = [{"role": "system", "content": "s"}]
    for i in range(20):
        msgs.append({"role": "tool", "content": "x" * 5000})
    history = compactor._format_history(msgs, 1, len(msgs))
    assert len(history) <= 32_000


def test_format_history_skips_system():
    compactor = ExploreCompactor(llm_port=MagicMock())
    msgs = [
        {"role": "system", "content": "system prompt"},
        {"role": "assistant", "content": "thinking"},
    ]
    history = compactor._format_history(msgs, 0, 2)
    assert "system prompt" not in history


def test_parse_sections_extracts_9():
    compactor = ExploreCompactor(llm_port=MagicMock())
    text = """## 1. Primary Objective
Goal here
## 2. Key Discoveries
- Entity (path): desc
## 3. Call Chains & Dependencies
- A→B
## 4. Reasoning Chain
- Because X
## 5. Variables & State
- v1
## 6. Completed Steps
- step1
## 7. Pending Actions
- pending1
## 8. Errors & Solutions
- none
## 9. Next Action
- next"""
    sections = compactor._parse_sections(text)
    assert len(sections) >= 8  # at least 8 of 9


def test_parse_sections_handles_partial():
    compactor = ExploreCompactor(llm_port=MagicMock())
    text = "## 1. Primary Objective\nSome goal\n## 9. Next Action\nDo stuff"
    sections = compactor._parse_sections(text)
    assert "Primary Objective" in sections
    assert "Next Action" in sections


def test_compaction_result_fields():
    result = CompactionResult(
        summary="test",
        key_findings=["f1"],
        call_chains=["c1"],
        covered_entities=["e1"],
        source_round_range=(1, 5),
        original_chars=1000,
        compressed_chars=100,
    )
    assert result.summary == "test"
    assert result.original_chars == 1000
