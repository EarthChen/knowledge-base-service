"""Test that pre_groups hints are injected into domain classification prompt."""

from wiki.graph_pre_grouper import PreGroup


def test_single_batch_prompt_contains_pre_groups():
    """When pre_groups are provided, prompt should contain 'Pre-grouping hints'."""
    from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

    planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
    planner._metadata_cache = {
        ("repo1", "ModA"): {"path": "com/meeting/ModA.java"},
        ("repo1", "ModB"): {"path": "com/meeting/ModB.java"},
    }
    planner._infrastructure_label = "Infrastructure"
    planner._module_summary = lambda repo, name: "summary"

    groups = [
        PreGroup(group_id=0, module_names=["ModA", "ModB"], directory_prefix="com/meeting"),
    ]

    prompt = planner._build_single_batch_prompt(
        "biz1",
        [("repo1", "ModA"), ("repo1", "ModB")],
        pre_groups=groups,
    )

    assert "Pre-grouping hints" in prompt
    assert "com/meeting" in prompt
    assert "ModA" in prompt
    assert "ModB" in prompt


def test_single_batch_prompt_without_pre_groups():
    """When pre_groups is None or empty, prompt should NOT contain pre-grouping section."""
    from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

    planner = CrossRepoBusinessDomainPlanner.__new__(CrossRepoBusinessDomainPlanner)
    planner._metadata_cache = {("repo1", "ModA"): {"path": "a.java"}}
    planner._infrastructure_label = "Infrastructure"
    planner._module_summary = lambda repo, name: "summary"

    prompt = planner._build_single_batch_prompt("biz1", [("repo1", "ModA")])
    assert "Pre-grouping hints" not in prompt
