"""Tests for DomainReviewAgent."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestDomainReviewAgentPropose:
    def test_propose_move_accepted(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={
                "family-core": [("repo", "FamilyService"), ("repo", "FamilyDao")],
                "intimacy-task": [("repo", "IntimacyTask"), ("repo", "FamilyTaskHandler")],
            },
            domain_display_names={},
            module_summaries={},
        )
        result = agent._propose_move("FamilyTaskHandler", "intimacy-task", "family-core", "prefix mismatch")
        assert result["status"] == "accepted"
        assert len(agent.pending_moves) == 1

    def test_propose_move_invalid_target(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={"family-core": [("repo", "FamilyService")]},
            domain_display_names={},
            module_summaries={},
        )
        result = agent._propose_move("FamilyService", "family-core", "nonexistent", "test")
        assert result["status"] == "rejected"
        assert "nonexistent" in result["reason"]

    def test_propose_move_module_not_found(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={
                "a": [("repo", "ModuleA")],
                "b": [("repo", "ModuleB")],
            },
            domain_display_names={},
            module_summaries={},
        )
        result = agent._propose_move("NonExistent", "a", "b", "test")
        assert result["status"] == "rejected"

    def test_move_limit_enforced(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock(), max_move_ratio=0.5)
        agent.set_domain_data(
            domain_mapping={
                "a": [("repo", "M1"), ("repo", "M2")],
                "b": [("repo", "M3"), ("repo", "M4")],
            },
            domain_display_names={},
            module_summaries={},
        )
        # 4 total modules * 0.5 = max 2 moves
        agent._propose_move("M3", "b", "a", "test1")
        agent._propose_move("M4", "b", "a", "test2")
        result = agent._propose_move("M1", "a", "b", "test3")
        assert result["status"] == "rejected"
        assert "limit" in result["reason"].lower()

    def test_propose_merge_accepted(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={
                "a": [("repo", "M1")],
                "b": [("repo", "M2")],
            },
            domain_display_names={},
            module_summaries={},
        )
        result = agent._propose_merge(["a", "b"], "a", "Combined Domain", "overlap")
        assert result["status"] == "accepted"

    def test_propose_rename_accepted(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={"a": [("repo", "M1")]},
            domain_display_names={"a": "Old Name"},
            module_summaries={},
        )
        result = agent._propose_rename("a", "New Name", "better name")
        assert result["status"] == "accepted"


class TestDomainReviewAgentApply:
    def test_apply_moves(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={
                "family": [("repo", "FamilyService"), ("repo", "FamilyDao")],
                "intimacy": [("repo", "IntimacyTask"), ("repo", "FamilyHandler")],
            },
            domain_display_names={},
            module_summaries={},
        )
        agent._propose_move("FamilyHandler", "intimacy", "family", "prefix")
        result = agent.apply_decisions()
        assert ("repo", "FamilyHandler") in result["family"]
        assert ("repo", "FamilyHandler") not in result["intimacy"]

    def test_apply_merges(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={
                "a": [("repo", "M1")],
                "b": [("repo", "M2")],
            },
            domain_display_names={},
            module_summaries={},
        )
        agent._propose_merge(["a", "b"], "a", "Merged", "test")
        result = agent.apply_decisions()
        assert "b" not in result
        assert ("repo", "M2") in result["a"]

    def test_empty_domain_removed(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_domain_data(
            domain_mapping={
                "a": [("repo", "M1")],
                "b": [("repo", "M2")],
            },
            domain_display_names={},
            module_summaries={},
        )
        agent._propose_move("M2", "b", "a", "test")
        result = agent.apply_decisions()
        assert "b" not in result

    def test_no_decisions_returns_original(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        original = {"a": [("repo", "M1")]}
        agent.set_domain_data(
            domain_mapping=original,
            domain_display_names={},
            module_summaries={},
        )
        result = agent.apply_decisions()
        assert result == original


class TestDomainReviewAgentTree:
    def test_propose_reparent_domain_moves_child(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        tree = [
            {
                "name": "relations",
                "display_name": "关系",
                "modules": [],
                "children": [
                    {
                        "name": "intimacy-core",
                        "display_name": "亲密度核心",
                        "modules": ["m1"],
                        "children": [],
                    },
                ],
            },
            {
                "name": "intimacy-task-execution",
                "display_name": "亲密度任务",
                "modules": ["m2"],
                "children": [],
            },
        ]
        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_tree_data(tree, {}, {})

        result = agent._propose_reparent_domain("intimacy-task-execution", "relations", "prefix family")
        assert result["status"] == "accepted"
        updated = agent.apply_tree_decisions()
        relations = [n for n in updated if n["name"] == "relations"][0]
        assert len(relations["children"]) == 2
        child_names = [c["name"] for c in relations["children"]]
        assert "intimacy-task-execution" in child_names

    def test_propose_reparent_promote_to_l1(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        tree = [
            {
                "name": "relations",
                "display_name": "关系",
                "modules": [],
                "children": [
                    {
                        "name": "intimacy-core",
                        "display_name": "亲密度",
                        "modules": ["m1"],
                        "children": [],
                    },
                ],
            },
        ]
        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_tree_data(tree, {}, {})

        result = agent._propose_reparent_domain("intimacy-core", None, "should be L1")
        assert result["status"] == "accepted"
        updated = agent.apply_tree_decisions()
        l1_names = [n["name"] for n in updated]
        assert "intimacy-core" in l1_names
        relations = [n for n in updated if n["name"] == "relations"][0]
        assert len(relations["children"]) == 0

    def test_propose_reparent_rejects_unknown_child(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        tree = [{"name": "a", "display_name": "A", "modules": ["m1"], "children": []}]
        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_tree_data(tree, {}, {})

        result = agent._propose_reparent_domain("nonexistent", "a", "reason")
        assert result["status"] == "rejected"

    def test_propose_reparent_rejects_unknown_parent(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        tree = [{"name": "a", "display_name": "A", "modules": ["m1"], "children": []}]
        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_tree_data(tree, {}, {})

        result = agent._propose_reparent_domain("a", "nonexistent", "reason")
        assert result["status"] == "rejected"

    def test_set_tree_data_deep_copies(self):
        """set_tree_data should not mutate the caller's tree."""
        from wiki.agents.domain_review_agent import DomainReviewAgent

        original_tree = [
            {
                "name": "parent",
                "display_name": "P",
                "modules": [],
                "children": [
                    {"name": "child-a", "display_name": "A", "modules": ["m1"], "children": []},
                ],
            },
        ]
        agent = DomainReviewAgent(llm=MagicMock())
        agent.set_tree_data(original_tree, {}, {})

        # Reparent child-a to L1
        agent._propose_reparent_domain("child-a", None, "test")
        agent.apply_tree_decisions()

        # Original tree should be unchanged
        assert len(original_tree[0]["children"]) == 1
        assert original_tree[0]["children"][0]["name"] == "child-a"


@pytest.mark.asyncio
async def test_tree_review_prompt_generation():
    """Tree review prompt should contain tree structure."""
    from wiki.nodes.graph_domain_decompose import _build_tree_review_prompt

    tree = [
        {"name": "relation", "display_name": "关系", "modules": [], "children": [
            {"name": "intimacy-relationship", "display_name": "亲密度关系", "modules": ["m1"], "children": []},
        ]},
        {"name": "intimacy-task-execution", "display_name": "亲密度任务", "modules": ["m2"], "children": []},
    ]
    prompt = _build_tree_review_prompt(tree)
    assert "relation" in prompt
    assert "intimacy-task-execution" in prompt
    assert "reparents" in prompt
