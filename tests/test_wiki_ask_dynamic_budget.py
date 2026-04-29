"""Tests for wiki ask dynamic context token budget."""

from wiki.ask import wiki_context_token_budget


def test_question_types_use_distinct_base_budgets():
    q = "sample"
    concept = wiki_context_token_budget(q, "concept")
    flow = wiki_context_token_budget(q, "flow")
    relation = wiki_context_token_budget(q, "relation")
    impact = wiki_context_token_budget(q, "impact")
    general = wiki_context_token_budget(q, "general")

    assert flow == relation
    assert flow > concept
    assert flow > impact
    assert impact == general


def test_question_length_increases_budget_within_cap():
    short_q = "hi"
    long_q = "word " * 400
    base = wiki_context_token_budget(short_q, "general")
    larger = wiki_context_token_budget(long_q, "general")
    assert larger > base
    assert larger <= 16000


def test_ask_budget_uses_resolver_proportions():
    from wiki.ask import wiki_context_token_budget_from_resolver
    from wiki.token_budget import TokenBudgetResolver

    r = TokenBudgetResolver(base=30_000)
    concept = wiki_context_token_budget_from_resolver("what is X?", "concept", r)
    flow = wiki_context_token_budget_from_resolver("how does X flow?", "flow", r)
    assert concept < flow

    r_small = TokenBudgetResolver(base=6_000)
    concept_small = wiki_context_token_budget_from_resolver("what is X?", "concept", r_small)
    assert concept_small < concept
