import pytest
from wiki.harness import WikiGenerationHarness


def test_harness_accepts_injected_domain_cache():
    shared_cache = {"existing-domain": "cached summary"}
    harness = WikiGenerationHarness(
        agent=None, graph_store=None, llm=None,
        domain_cache=shared_cache,
    )
    assert harness.domain_cache is shared_cache
    assert harness.domain_cache["existing-domain"] == "cached summary"


def test_harness_defaults_to_empty_cache_when_none():
    harness = WikiGenerationHarness(
        agent=None, graph_store=None, llm=None,
    )
    assert harness.domain_cache == {}


def test_harness_domain_cache_none_explicit():
    harness = WikiGenerationHarness(
        agent=None, graph_store=None, llm=None,
        domain_cache=None,
    )
    assert harness.domain_cache == {}
