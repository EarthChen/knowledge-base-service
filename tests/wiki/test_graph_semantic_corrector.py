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


def _make_review_llm():
    """Create an LLM mock suitable for review_global_consistency tests."""
    llm = AsyncMock()
    llm.generate.return_value = '{"merges": [], "renames": [], "moves": []}'
    return llm


def _get_prompt(llm):
    """Extract the prompt string passed to llm.generate."""
    return llm.generate.call_args[0][0]


class TestReviewGlobalConsistency:
    @pytest.mark.asyncio
    async def test_merge_overlapping_domains(self):
        llm = _make_review_llm()
        llm.generate.return_value = (
            '{"merges": [{"sources": ["intimacy-rel", "private-friends"], '
            '"target": "intimacy-rel", "new_display_name": "亲密关系", "reason": "same business"}], '
            '"renames": [], "moves": []}'
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
        llm = _make_review_llm()
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

    @pytest.mark.asyncio
    async def test_global_review_passes_top_10_modules(self):
        """Task 4: listing should include top 10 modules per domain (not 5)."""
        llm = _make_review_llm()
        corrector = GraphSemanticCorrector(llm)

        # Domain with 12 modules — expect 10 in the prompt
        pairs = [("r", f"Mod{i:02d}") for i in range(12)]
        domain_mapping = {
            "big-domain": pairs,
            "other": [("r", "OtherMod")],  # second domain so we don't early-return
        }
        domain_display = {"big-domain": "大域", "other": "其他"}

        await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )

        prompt = _get_prompt(llm)
        # Should contain 10 modules (Mod00..Mod09 sorted)
        assert "Mod00" in prompt
        assert "Mod09" in prompt
        # Mod10 should NOT be in the prompt (only top 10)
        assert "Mod10" not in prompt

    @pytest.mark.asyncio
    async def test_global_review_passes_all_when_fewer_than_10(self):
        """Task 4: domains with <10 modules should pass all of them."""
        llm = _make_review_llm()
        corrector = GraphSemanticCorrector(llm)

        pairs = [("r", f"Mod{i}") for i in range(7)]
        domain_mapping = {
            "small-domain": pairs,
            "other": [("r", "OtherMod")],
        }
        domain_display = {"small-domain": "小域", "other": "其他"}

        await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )

        prompt = _get_prompt(llm)
        for i in range(7):
            assert f"Mod{i}" in prompt

    @pytest.mark.asyncio
    async def test_global_review_includes_shortened_path_and_summary(self):
        """Task 4: each module entry should include shortened path and summary."""
        llm = _make_review_llm()
        corrector = GraphSemanticCorrector(llm)

        domain_mapping = {
            "auth": [("r", "LoginService"), ("r", "TokenValidator")],
            "billing": [("r", "InvoiceService")],
        }
        domain_display = {"auth": "认证", "billing": "计费"}
        module_paths = {
            "LoginService": "com/example/auth/LoginService.java",
            "TokenValidator": "com/example/auth/token/TokenValidator.java",
        }
        module_summaries = {
            "LoginService": "Handles user login flow",
            "TokenValidator": "Validates JWT tokens",
        }

        await corrector.review_global_consistency(
            domain_mapping, domain_display,
            module_paths=module_paths, module_summaries=module_summaries,
        )

        prompt = _get_prompt(llm)
        # Shortened paths (last 3 levels)
        assert "auth/LoginService.java" in prompt
        assert "auth/token/TokenValidator.java" in prompt
        # Summaries
        assert "Handles user login flow" in prompt
        assert "Validates JWT tokens" in prompt

    @pytest.mark.asyncio
    async def test_global_review_no_path_or_summary_shown_when_missing(self):
        """When path/summary dicts are empty, listing still works without them."""
        llm = _make_review_llm()
        corrector = GraphSemanticCorrector(llm)

        domain_mapping = {
            "auth": [("r", "LoginService")],
            "billing": [("r", "InvoiceService")],
        }
        domain_display = {"auth": "认证", "billing": "计费"}

        await corrector.review_global_consistency(
            domain_mapping, domain_display,
            module_paths={}, module_summaries={},
        )

        prompt = _get_prompt(llm)
        assert "LoginService" in prompt
        # No path or summary annotations should appear
        assert "[path:" not in prompt
        # Summary separator " -- " should not appear
        assert " -- " not in prompt
