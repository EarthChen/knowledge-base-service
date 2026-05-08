"""Tests for GatheredFacts and tiered distill logic."""
import pytest


class TestGatheredFacts:
    def test_add_fact(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "ModuleA: handles user auth")
        assert "概述" in facts.facts
        assert len(facts.facts["概述"]) == 1
        assert facts.total_chars > 0

    def test_distill_simple_budget(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "A" * 2000)
        facts.add("核心业务流程", "query_call_chain", "B" * 2000)
        result = facts.distill(complexity_level="simple")
        assert "## 概述" in result
        assert "## 核心业务流程" in result
        assert "[...truncated]" in result

    def test_distill_complex_budget_no_truncation(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "A" * 3000)
        result = facts.distill(complexity_level="complex")
        assert "[...truncated]" not in result

    def test_distill_injects_domain_summaries(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "test content")
        summaries = ["Domain: Auth\nModules: UserService\nSummary: handles login"]
        result = facts.distill(complexity_level="moderate", domain_summaries=summaries)
        assert "相关域参考" in result
        assert "Auth" in result

    def test_distill_empty_facts(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        result = facts.distill(complexity_level="moderate")
        assert result == ""

    def test_multiple_facts_per_section_combined(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "tool1", "fact1")
        facts.add("概述", "tool2", "fact2")
        result = facts.distill(complexity_level="moderate")
        assert "fact1" in result
        assert "fact2" in result
