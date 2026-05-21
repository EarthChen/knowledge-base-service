"""Tests for GraphSemanticCorrector."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wiki.graph_semantic_corrector import GraphSemanticCorrector


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def corrector(mock_llm):
    return GraphSemanticCorrector(mock_llm)


@pytest.mark.asyncio
async def test_correct_module_assignments_moves_misplaced_module(corrector, mock_llm):
    """ClosedFriendTaskHandler should be moved from family-task to intimacy-mgmt."""
    domain_mapping = {
        "family-task": [
            ("repo1", "FamilyTaskHandler"),
            ("repo1", "FamilyTaskValidator"),
            ("repo1", "ClosedFriendTaskHandler"),
        ],
        "intimacy-mgmt": [("repo1", "IntimacyService"), ("repo1", "IntimacyGiftHandler")],
    }
    domain_display_names = {"family-task": "家族任务管理", "intimacy-mgmt": "亲密关系管理"}
    module_paths = {
        "FamilyTaskHandler": "com/example/family/task/FamilyTaskHandler.java",
        "FamilyTaskValidator": "com/example/family/task/FamilyTaskValidator.java",
        "ClosedFriendTaskHandler": "com/example/closedfriend/task/ClosedFriendTaskHandler.java",
        "IntimacyService": "com/example/intimacy/IntimacyService.java",
        "IntimacyGiftHandler": "com/example/intimacy/gift/IntimacyGiftHandler.java",
    }

    mock_llm.generate.return_value = json.dumps({
        "moves": [
            {
                "module": "ClosedFriendTaskHandler",
                "from_domain": "family-task",
                "to_domain": "intimacy-mgmt",
                "reason": "ClosedFriend belongs to intimacy",
            }
        ]
    })

    result = await corrector.correct_module_assignments(
        domain_mapping, domain_display_names, module_paths, {}
    )

    assert ("repo1", "ClosedFriendTaskHandler") not in result["family-task"]
    assert ("repo1", "ClosedFriendTaskHandler") in result["intimacy-mgmt"]
    assert len(result["family-task"]) == 2
    assert len(result["intimacy-mgmt"]) == 3


@pytest.mark.asyncio
async def test_correct_no_moves_needed(corrector, mock_llm):
    """When LLM finds no misplacements, domain_mapping is unchanged."""
    domain_mapping = {
        "family": [("repo1", "FamilyService")],
    }
    mock_llm.generate.return_value = json.dumps({"moves": []})

    result = await corrector.correct_module_assignments(
        domain_mapping, {"family": "家族"}, {}, {}
    )

    assert result == domain_mapping


@pytest.mark.asyncio
async def test_correct_llm_failure_returns_original(corrector, mock_llm):
    """When LLM fails, return original domain_mapping unchanged."""
    domain_mapping = {
        "family": [("repo1", "FamilyService")],
    }
    mock_llm.generate.side_effect = Exception("LLM down")

    result = await corrector.correct_module_assignments(
        domain_mapping, {"family": "家族"}, {}, {}
    )

    assert result == domain_mapping


@pytest.mark.asyncio
async def test_correct_invalid_target_domain_skipped(corrector, mock_llm):
    """Moves targeting non-existent domains are skipped."""
    domain_mapping = {
        "family": [("repo1", "FamilyService"), ("repo1", "SomeModule")],
    }
    mock_llm.generate.return_value = json.dumps({
        "moves": [
            {"module": "SomeModule", "from_domain": "family", "to_domain": "nonexistent", "reason": "test"}
        ]
    })

    result = await corrector.correct_module_assignments(
        domain_mapping, {"family": "家族"}, {}, {}
    )

    assert ("repo1", "SomeModule") in result["family"]


@pytest.mark.asyncio
async def test_correct_move_cap_30_percent(corrector, mock_llm):
    """At most 30% of total modules can be moved in one correction."""
    modules = [(f"repo1", f"Module{i}") for i in range(10)]
    domain_mapping = {"domain-a": modules}
    moves = [
        {"module": f"Module{i}", "from_domain": "domain-a", "to_domain": "domain-b", "reason": "test"}
        for i in range(10)
    ]
    mock_llm.generate.return_value = json.dumps({"moves": moves})

    result = await corrector.correct_module_assignments(
        {**domain_mapping, "domain-b": []},
        {"domain-a": "A", "domain-b": "B"},
        {},
        {},
    )

    moved = len([m for m in modules if m not in result.get("domain-a", [])])
    assert moved <= 3  # 30% of 10


@pytest.mark.asyncio
async def test_merge_similar_domains(corrector, mock_llm):
    """Domains with overlapping business meaning should be merged."""
    domain_infos = [
        {"slug": "closed-friend-service", "display_name": "私密好友服务", "module_count": 5},
        {"slug": "closed-friend-market", "display_name": "私密好友市场", "module_count": 3},
        {"slug": "family-system", "display_name": "家族系统", "module_count": 10},
    ]
    mock_llm.generate.return_value = json.dumps({
        "merges": [
            {
                "sources": ["closed-friend-service", "closed-friend-market"],
                "target": "closed-friend-service",
                "reason": "same business",
            }
        ]
    })

    result = await corrector.merge_similar_domains(domain_infos)

    assert len(result) == 1
    assert result[0]["sources"] == ["closed-friend-service", "closed-friend-market"]
    assert result[0]["target"] == "closed-friend-service"


@pytest.mark.asyncio
async def test_merge_no_merges_needed(corrector, mock_llm):
    """When no merges needed, return empty list."""
    mock_llm.generate.return_value = json.dumps({"merges": []})

    result = await corrector.merge_similar_domains([
        {"slug": "family", "display_name": "家族", "module_count": 5},
    ])

    assert result == []


@pytest.mark.asyncio
async def test_merge_llm_failure_returns_empty(corrector, mock_llm):
    """When LLM fails, return empty list (no merges)."""
    mock_llm.generate.side_effect = Exception("LLM down")

    result = await corrector.merge_similar_domains([
        {"slug": "family", "display_name": "家族", "module_count": 5},
    ])

    assert result == []


class TestReviewGlobalConsistency:
    @pytest.mark.asyncio
    async def test_merge_overlapping_domains(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value='{"merges": [{"sources": ["intimacy-rel", "private-friends"], "target": "intimacy-rel", "new_display_name": "亲密关系", "reason": "same business"}], "renames": [], "moves": []}'
        )
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {
            "intimacy-rel": [("r", "IntimacyService"), ("r", "IntimacyTask")],
            "private-friends": [("r", "ClosedFriendHandler")],
            "family-system": [("r", "FamilyService")],
        }
        domain_display = {"intimacy-rel": "亲密关系", "private-friends": "私密好友", "family-system": "家族系统"}
        new_mapping, new_display = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )
        assert "private-friends" not in new_mapping
        assert "intimacy-rel" in new_mapping
        assert ("r", "ClosedFriendHandler") in new_mapping["intimacy-rel"]
        assert new_display.get("intimacy-rel") == "亲密关系"

    @pytest.mark.asyncio
    async def test_no_changes_needed(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value='{"merges": [], "renames": [], "moves": []}')
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {"a": [("r", "X")], "b": [("r", "Y")]}
        domain_display = {"a": "域A", "b": "域B"}
        new_mapping, new_display = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )
        assert new_mapping == domain_mapping
        assert new_display == domain_display

    @pytest.mark.asyncio
    async def test_llm_none_returns_unchanged(self):
        corrector = GraphSemanticCorrector(None)
        domain_mapping = {"a": [("r", "X")]}
        domain_display = {"a": "域A"}
        new_mapping, new_display = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )
        assert new_mapping == domain_mapping
