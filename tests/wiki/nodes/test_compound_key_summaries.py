"""Tests for compound-key module_summaries and summary_text in classification."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestModuleSummariesCompoundKey:
    """compose_leaf_modules_node should key summaries by repo|name."""

    @pytest.mark.asyncio
    async def test_compound_key_prevents_collision(self):
        """Two repos with same module name produce separate summaries."""
        from wiki.nodes.compose import compose_leaf_modules_node

        state = {
            "modules": {
                "repo_a": [
                    {"properties": {"name": "UserService", "repository": "repo_a", "path": "repo_a/user.py"}, "labels": ["Module"]},
                ],
                "repo_b": [
                    {"properties": {"name": "UserService", "repository": "repo_b", "path": "repo_b/user.py"}, "labels": ["Module"]},
                ],
            },
            "entity_roles": {},
        }
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="summary of module")
        configurable = {"llm": mock_llm, "graph_store": None}

        with patch("wiki.nodes.compose._generate_single_module_summary") as mock_gen:
            long_summary_a = "Repo A service " * 12  # >= 100 chars to skip round 2
            long_summary_b = "Repo B service " * 12
            mock_gen.side_effect = [
                ("UserService", {"summary_text": long_summary_a, "key_methods": []}),
                ("UserService", {"summary_text": long_summary_b, "key_methods": []}),
            ]
            with patch("wiki.nodes.compose.PipelineConcurrency") as mock_pc:
                mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
                result = await compose_leaf_modules_node(state, {"configurable": configurable})

        summaries = result.get("module_summaries", {})
        assert "repo_a|UserService" in summaries
        assert "repo_b|UserService" in summaries
        assert summaries["repo_a|UserService"]["summary_text"] == long_summary_a
        assert summaries["repo_b|UserService"]["summary_text"] == long_summary_b
        assert mock_gen.call_count == 2


class TestEnrichedSignalSuffix:
    """_enriched_signal_suffix should include summary_text."""

    def test_includes_summary_text(self):
        from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

        planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
        signals = {
            ("repo_a", "UserService"): {
                "summary_text": "Handles user registration and auth",
                "key_methods": ["register", "login"],
                "callees": ["DatabaseRepo"],
                "fan_in": 5,
            }
        }
        result = planner._enriched_signal_suffix("repo_a", "UserService", signals)
        assert "Handles user registration" in result
        assert "methods:" in result

    def test_summary_text_absent_falls_back(self):
        from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

        planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
        signals = {
            ("repo_a", "UserService"): {
                "key_methods": ["register"],
                "callees": [],
                "fan_in": 0,
            }
        }
        result = planner._enriched_signal_suffix("repo_a", "UserService", signals)
        assert "methods:" in result
        assert "Handles" not in result
