"""Tests for cross-repo domain planner prompt redesign (anchor, slugs, enriched signals)."""

import inspect

from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


class TestPromptRedesign:
    """Test that prompts include anchor context and require slug output."""

    def test_single_batch_prompt_includes_anchors(self):
        """The single batch prompt should include anchor context when provided."""
        planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
        planner._metadata_cache = {("repo1", "ModA"): {"path": "a.java"}}
        planner._infrastructure_label = "__infrastructure__"
        planner._module_summary = lambda repo, name: "summary"

        prompt = planner._build_single_batch_prompt(
            business_id="test",
            pairs_in_order=[("repo1", "ModA")],
            pre_groups=None,
            anchor_context="ANCHOR_DOMAINS_HERE",
        )
        assert "ANCHOR_DOMAINS_HERE" in prompt

    def test_classify_accepts_anchor_context(self):
        """classify() should accept anchor_context keyword argument."""
        sig = inspect.signature(CrossRepoBusinessDomainPlanner.classify)
        assert "anchor_context" in sig.parameters

    def test_classify_accepts_enriched_signals(self):
        """classify() should accept enriched_signals keyword argument."""
        sig = inspect.signature(CrossRepoBusinessDomainPlanner.classify)
        assert "enriched_signals" in sig.parameters

    def test_classify_incremental_accepts_enriched_signals(self):
        """classify_incremental() should accept enriched_signals keyword argument."""
        sig = inspect.signature(CrossRepoBusinessDomainPlanner.classify_incremental)
        assert "enriched_signals" in sig.parameters

    def test_build_single_batch_prompt_accepts_enriched_signals(self):
        """_build_single_batch_prompt should accept enriched_signals."""
        sig = inspect.signature(CrossRepoBusinessDomainPlanner._build_single_batch_prompt)
        assert "enriched_signals" in sig.parameters

    def test_slug_output_format_instruction(self):
        """The prompt should instruct LLM to output slug + display_name."""
        planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
        planner._metadata_cache = {("repo1", "ModA"): {"path": "a.java"}}
        planner._infrastructure_label = "__infrastructure__"
        planner._module_summary = lambda repo, name: "some service"

        prompt = planner._build_single_batch_prompt(
            business_id="test",
            pairs_in_order=[("repo1", "ModA")],
            pre_groups=None,
            anchor_context="",
        )
        pl = prompt.lower()
        assert "domain_slug" in pl
        assert "domain_display_name" in pl

    def test_enriched_signals_in_prompt(self):
        """When enriched_signals is set, prompt module text should include signal hints."""
        planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
        planner._metadata_cache = {("repo1", "ModA"): {"path": "a.java", "business_summary": "svc"}}
        planner._infrastructure_label = "__infrastructure__"
        planner._module_summary = lambda repo, name: "some service"

        enriched = {
            ("repo1", "ModA"): {
                "key_methods": ["foo", "bar", "baz", "qux"],
                "callees": ["X", "Y", "Z", "W"],
                "fan_in": 5,
            }
        }
        prompt = planner._build_single_batch_prompt(
            business_id="test",
            pairs_in_order=[("repo1", "ModA")],
            pre_groups=None,
            anchor_context="",
            enriched_signals=enriched,
        )
        assert "[methods:" in prompt
        assert "foo" in prompt
        assert "[calls:" in prompt
        assert "[fan_in: 5]" in prompt


def test_cross_repo_map_new_domains_format_normalized_slug():
    """Parser accepts domains array with slug/display_name; keys use display name."""
    data = {
        "domains": [
            {
                "domain_slug": "Payment Processing!",
                "domain_display_name": "Payments",
                "modules": [["repo-a", "billing"]],
            }
        ]
    }
    parsed = CrossRepoBusinessDomainPlanner._cross_repo_map_from_dict(data)
    assert "Payments" in parsed
    assert parsed["Payments"] == [("repo-a", "billing")]
