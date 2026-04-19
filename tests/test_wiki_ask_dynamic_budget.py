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
