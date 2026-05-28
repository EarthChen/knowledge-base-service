"""Tests for compound-key handling in GraphSemanticCorrector moves and corrector inputs."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wiki.graph_semantic_corrector import GraphSemanticCorrector
from wiki.nodes.graph_domain_decompose import (
    _build_module_summaries_flat_for_corrector,
    _build_paths_for_corrector,
    _compound_key,
)


class TestCorrectorMoveHomonyms:
    """J-3: moves should resolve (repo, module) from the source domain, not last-repo-wins."""

    @pytest.mark.asyncio
    async def test_move_homonym_uses_source_domain_pair(self):
        llm = AsyncMock(spec=["complete_json"])
        llm.complete_json = AsyncMock(return_value={
            "merges": [],
            "renames": [],
            "moves": [{
                "module": "AuthService",
                "from": "domain-a",
                "to": "domain-b",
                "reason": "misplaced",
            }],
            "summary": "",
        })
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {
            "domain-a": [("repo-a", "AuthService")],
            "domain-b": [("repo-b", "AuthService"), ("repo-b", "BillingService")],
        }
        domain_display = {"domain-a": "域A", "domain-b": "域B"}

        new_mapping, _ = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )

        assert ("repo-a", "AuthService") in new_mapping["domain-b"]
        assert ("repo-a", "AuthService") not in new_mapping.get("domain-a", [])
        assert ("repo-b", "AuthService") in new_mapping["domain-b"]
        assert ("repo-b", "BillingService") in new_mapping["domain-b"]

    @pytest.mark.asyncio
    async def test_move_unique_name_works_as_before(self):
        llm = AsyncMock(spec=["complete_json"])
        llm.complete_json = AsyncMock(return_value={
            "merges": [],
            "renames": [],
            "moves": [{
                "module": "UniqueService",
                "from": "domain-a",
                "to": "domain-b",
                "reason": "misplaced",
            }],
            "summary": "",
        })
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {
            "domain-a": [("repo-a", "UniqueService")],
            "domain-b": [("repo-b", "OtherService")],
        }
        domain_display = {"domain-a": "域A", "domain-b": "域B"}

        new_mapping, _ = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )

        assert ("repo-a", "UniqueService") in new_mapping["domain-b"]
        assert "domain-a" not in new_mapping or ("repo-a", "UniqueService") not in new_mapping.get("domain-a", [])


class TestCorrectorInputCompoundKeys:
    """J-4: module_summaries_flat and paths_for_corrector should use compound keys."""

    def test_module_summaries_flat_homonyms(self):
        biz_modules = [("repo-a", "UserService"), ("repo-b", "UserService")]
        module_summaries_raw = {
            _compound_key("repo-a", "UserService"): {"summary_text": "Users in repo A"},
            _compound_key("repo-b", "UserService"): {"summary_text": "Users in repo B"},
        }

        flat = _build_module_summaries_flat_for_corrector(biz_modules, module_summaries_raw)

        assert flat["repo-a|UserService"] == "Users in repo A"
        assert flat["repo-b|UserService"] == "Users in repo B"
        assert "UserService" not in flat

    def test_module_summaries_flat_unique_name_keeps_bare_key(self):
        biz_modules = [("repo-a", "OrderService")]
        module_summaries_raw = {
            _compound_key("repo-a", "OrderService"): {"summary_text": "Order handling"},
        }

        flat = _build_module_summaries_flat_for_corrector(biz_modules, module_summaries_raw)

        assert flat["repo-a|OrderService"] == "Order handling"
        assert flat["OrderService"] == "Order handling"

    def test_paths_for_corrector_homonyms(self):
        biz_modules = [("repo-a", "UserService"), ("repo-b", "UserService")]
        module_paths = {
            "repo-a|UserService": "a/user.py",
            "repo-b|UserService": "b/user.py",
        }

        paths = _build_paths_for_corrector(biz_modules, module_paths)

        assert paths["repo-a|UserService"] == "a/user.py"
        assert paths["repo-b|UserService"] == "b/user.py"
        assert "UserService" not in paths

    def test_paths_for_corrector_unique_name_keeps_bare_key(self):
        biz_modules = [("repo-a", "OrderService")]
        module_paths = {"repo-a|OrderService": "a/order.py"}

        paths = _build_paths_for_corrector(biz_modules, module_paths)

        assert paths["repo-a|OrderService"] == "a/order.py"
        assert paths["OrderService"] == "a/order.py"
