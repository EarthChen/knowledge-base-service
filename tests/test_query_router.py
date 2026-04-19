"""Tests for query routing and intent-based hybrid weights."""

from __future__ import annotations

import pytest

from query.query_router import route_query


def test_concept_strategy_weights() -> None:
    s = route_query("what is a singleton pattern")
    assert s.query_type == "concept"
    assert s.semantic_weight == pytest.approx(1.5)
    assert s.keyword_weight == pytest.approx(0.5)
    assert s.expand_graph is True
    assert s.entity_priority == []


def test_flow_strategy_weights() -> None:
    s = route_query("how does the login process work")
    assert s.query_type == "flow"
    assert s.semantic_weight == pytest.approx(1.0)
    assert s.keyword_weight == pytest.approx(1.0)
    assert s.expand_graph is True
    assert s.entity_priority == ["Function"]


def test_relation_strategy_weights() -> None:
    s = route_query("difference between Redis and Memcached")
    assert s.query_type == "relation"
    assert s.keyword_weight == pytest.approx(1.5)
    assert s.semantic_weight == pytest.approx(1.0)


def test_impact_strategy_weights() -> None:
    s = route_query("what depends on the payment module")
    assert s.query_type == "impact"
    assert s.keyword_weight == pytest.approx(1.5)
    assert s.semantic_weight == pytest.approx(0.5)


def test_general_strategy_weights() -> None:
    s = route_query("summarize recent changes")
    assert s.query_type == "general"
    assert s.keyword_weight == pytest.approx(1.5)
    assert s.semantic_weight == pytest.approx(1.0)


def test_fqn_like_query_boosts_keyword_weight() -> None:
    baseline = route_query("what is the checkout experience")
    boosted = route_query("what is com.acme.foo.BarService")
    assert baseline.query_type == boosted.query_type == "concept"
    assert boosted.keyword_weight > baseline.keyword_weight
    assert boosted.keyword_weight == pytest.approx(0.5 * 1.25)


def test_camel_case_boosts_keyword_weight() -> None:
    baseline = route_query("describe the handler")
    boosted = route_query("describe loginV2Handler behavior")
    assert boosted.keyword_weight > baseline.keyword_weight


def test_chinese_relation_classification() -> None:
    s = route_query("Redis 和 MySQL 有什么区别")
    assert s.query_type == "relation"


def test_chinese_concept_classification() -> None:
    s = route_query("什么是 OAuth2 授权码模式")
    assert s.query_type == "concept"


def test_chinese_flow_classification() -> None:
    s = route_query("支付流程是怎么走的")
    assert s.query_type == "flow"
