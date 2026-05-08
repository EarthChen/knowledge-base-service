"""Test that CCB + Agent-Driven fusion: CCB always runs first, Agent uses CCB context."""
import inspect


def test_compose_runs_ccb_before_agent():
    """In _compose_single_leaf_domain, CCB context building should appear before Agent check."""
    from wiki.nodes import compose as compose_mod

    source = inspect.getsource(compose_mod._compose_single_leaf_domain)

    ccb_pos = source.find("ContentContextBuilder")
    agent_pos = source.find("AgentConfig")

    assert ccb_pos != -1, "ContentContextBuilder should be used in _compose_single_leaf_domain"
    assert agent_pos != -1, "AgentConfig should be used in _compose_single_leaf_domain"
    assert ccb_pos < agent_pos, (
        "CCB context building should appear BEFORE AgentConfig check — "
        "CCB must always run first to provide baseline context to Agent"
    )


def test_agent_uses_format_summary_for_agent():
    """Agent path should use format_summary_for_agent for rich baseline context."""
    from wiki.nodes import compose as compose_mod

    source = inspect.getsource(compose_mod._compose_single_leaf_domain)
    assert "format_summary_for_agent" in source, (
        "Agent path should use format_summary_for_agent to pass CCB context"
    )


def test_format_summary_includes_module_summaries():
    """format_summary_for_agent should include module_leaf_summaries section."""
    from wiki.content_context_builder import EnrichedDomainContext

    ctx = EnrichedDomainContext(domain_name="TestDomain", parent_domain="root")
    ctx.module_leaf_summaries = {"ModA": "Handles auth", "ModB": "Handles payments"}
    summary = ctx.format_summary_for_agent(max_chars=6000)
    assert "ModA" in summary
    assert "Handles auth" in summary


def test_format_summary_includes_domain_description():
    """format_summary_for_agent should include domain_description when present."""
    from wiki.content_context_builder import EnrichedDomainContext

    ctx = EnrichedDomainContext(domain_name="TestDomain", parent_domain="root")
    ctx.domain_description = "This domain handles user authentication flows"
    summary = ctx.format_summary_for_agent(max_chars=6000)
    assert "Domain Description" in summary
    assert "user authentication" in summary


def test_baseline_str_limit_increased():
    """page_agent.generate should use baseline_str with > 2000 char limit."""
    from wiki import page_agent

    source = inspect.getsource(page_agent.WikiPageAgent.generate)
    assert "[:2000]" not in source, "baseline_str should no longer truncate at 2000"
