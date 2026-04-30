from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.domain_complexity import DomainComplexity, DomainComplexityScorer
from wiki.topic_page_composer import TopicPageComposer


def _entity(name: str, *, methods: list[str] | None = None, calls: list[str] | None = None, loc: int = 0) -> dict:
    return {
        "name": name,
        "summary": f"{name} svc",
        "methods": methods or [],
        "calls": calls or [],
        "loc": loc,
    }


def test_low_complexity_domain():
    """Few entities with sparse methods/calls → LOW."""
    scorer = DomainComplexityScorer()
    domain = {
        "name": "small",
        "biz_entities": [
            _entity("A", methods=["m1"], calls=["X"], loc=50),
            _entity("B", methods=["m2"], calls=[], loc=80),
            _entity("C", methods=["m3"], calls=["Y"], loc=70),
        ],
    }
    m = scorer.score(domain)
    assert m.complexity == DomainComplexity.LOW
    assert m.entity_count == 3


def test_medium_complexity_domain():
    """Eight entities with moderate methods/calls → MEDIUM."""
    scorer = DomainComplexityScorer()
    entities = []
    for i in range(8):
        methods = [f"m{i}_{j}" for j in range(5)]
        calls = [f"C{k}" for k in range(i * 3, i * 3 + 5)]
        entities.append(_entity(f"S{i}", methods=methods, calls=calls, loc=120))
    domain = {"name": "mid", "biz_entities": entities}
    m = scorer.score(domain)
    assert m.complexity == DomainComplexity.MEDIUM
    assert m.entity_count == 8


def test_high_complexity_domain():
    """Many entities with dense methods/calls and high LOC → HIGH."""
    scorer = DomainComplexityScorer()
    entities = []
    for i in range(20):
        methods = [f"m{i}_{j}" for j in range(18)]
        calls = [f"C{k}" for k in range(i * 12, i * 12 + 25)]
        entities.append(_entity(f"H{i}", methods=methods, calls=calls, loc=450))
    domain = {"name": "heavy", "biz_entities": entities}
    m = scorer.score(domain)
    assert m.complexity == DomainComplexity.HIGH
    assert m.entity_count == 20


def test_scorer_with_empty_domain():
    scorer = DomainComplexityScorer()
    m = scorer.score({"name": "empty", "biz_entities": []})
    assert m.complexity == DomainComplexity.LOW
    assert m.raw_score == 0.0


def test_adaptive_thresholds_override():
    domain = {"name": "x", "biz_entities": [_entity("Only", methods=["a"], calls=[], loc=0)]}
    default_scorer = DomainComplexityScorer()
    assert default_scorer.score(domain).complexity == DomainComplexity.LOW

    strict_high = DomainComplexityScorer(low_threshold=0.5, high_threshold=1.0)
    assert strict_high.score(domain).complexity == DomainComplexity.HIGH

    strict_medium = DomainComplexityScorer(low_threshold=0.5, high_threshold=500.0)
    assert strict_medium.score(domain).complexity == DomainComplexity.MEDIUM


@pytest.mark.asyncio
async def test_topic_page_composer_uses_complexity():
    """Mock LLM: LOW → single-page path; MEDIUM → overview + split; HIGH → grouping first."""

    async def run_low():
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="# L\n\n## 业务概述\nx\n")
        composer = TopicPageComposer(llm, token_budget=8000)
        domain = {
            "name": "low-domain",
            "parent": "root",
            "biz_entities": [
                _entity("E1", methods=["a"], calls=[], loc=10),
                _entity("E2", methods=["b"], calls=[], loc=10),
                _entity("E3", methods=["c"], calls=[], loc=10),
            ],
            "data_models": [],
            "sibling_summaries": [],
        }
        pages = await composer.compose_leaf_domain(domain)
        assert len(pages) == 1
        assert llm.generate.await_count == 1
        low_prompt = llm.generate.await_args_list[0].args[0]
        assert "精简" in low_prompt or "简要" in low_prompt

    async def run_medium():
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value="# body\n")
        composer = TopicPageComposer(llm, token_budget=8000)
        entities = []
        for i in range(8):
            methods = [f"m{i}_{j}" for j in range(5)]
            calls = [f"C{k}" for k in range(i * 3, i * 3 + 5)]
            entities.append(_entity(f"S{i}", methods=methods, calls=calls, loc=120))
        domain = {
            "name": "med-domain",
            "parent": "root",
            "biz_entities": entities,
            "data_models": [],
            "sibling_summaries": [],
        }
        pages = await composer.compose_leaf_domain(domain)
        assert len(pages) >= 2
        assert any(p["page_type"] == "domain_overview" for p in pages)
        overview_calls = [c for c in llm.generate.await_args_list if "domain overview" in c.args[0].lower() or "域概览" in c.args[0]]
        assert len(overview_calls) >= 1
        token_budgets = [c.kwargs.get("max_tokens") for c in llm.generate.await_args_list]
        assert all(t == 8000 for t in token_budgets)

    async def run_high():
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=[
            '[{"name": "g1", "entities": ["H0","H1"]}, {"name": "g2", "entities": ["H2"]}]',
            "# ov\n",
            "# p1\n",
            "# p2\n",
        ])
        composer = TopicPageComposer(llm, token_budget=8000)
        entities = []
        for i in range(20):
            methods = [f"m{i}_{j}" for j in range(18)]
            calls = [f"C{k}" for k in range(i * 12, i * 12 + 25)]
            entities.append(_entity(f"H{i}", methods=methods, calls=calls, loc=450))
        domain = {
            "name": "hi-domain",
            "parent": "root",
            "biz_entities": entities,
            "data_models": [],
            "sibling_summaries": [],
        }
        pages = await composer.compose_leaf_domain(domain)
        assert len(pages) >= 3
        first_prompt = llm.generate.await_args_list[0].args[0]
        assert "Group these" in first_prompt or "logical sub-groups" in first_prompt
        high_token_calls = [c for c in llm.generate.await_args_list if c.kwargs.get("max_tokens") == 12000]
        assert len(high_token_calls) >= 1

    await run_low()
    await run_medium()
    await run_high()
