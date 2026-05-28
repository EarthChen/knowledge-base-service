"""Tests for F11: large-domain topic context overflow fixes."""
from __future__ import annotations

from unittest.mock import MagicMock

from wiki.domain_doc_agent import _filter_baseline_for_topic
from wiki.nodes.domain_compose import _scale_explore_params
from wiki.page_agent import WorkingMemory


def _sample_baseline() -> str:
    return "\n\n".join(
        [
            "## 支付域",
            "处理支付与退款的核心业务域。",
            "### 模块列表",
            "- **OrderService**: 订单服务",
            "- **PaymentService**: 支付服务",
            "- **RefundService**: 退款服务",
            "### 模块依赖拓扑",
            "- OrderService → PaymentService",
            "- PaymentService → RefundService",
            "- OtherModule → ExternalApi",
            "## 其他章节",
            "应完整保留。",
        ]
    )


def test_filter_baseline_for_topic_keeps_relevant_modules() -> None:
    baseline = _sample_baseline()
    result = _filter_baseline_for_topic(baseline, {"OrderService", "PaymentService"})
    assert "- **OrderService**" in result
    assert "- **PaymentService**" in result
    assert "- **RefundService**" not in result


def test_filter_baseline_for_topic_keeps_relevant_edges() -> None:
    baseline = _sample_baseline()
    result = _filter_baseline_for_topic(baseline, {"PaymentService"})
    assert "OrderService → PaymentService" in result
    assert "PaymentService → RefundService" in result
    assert "OtherModule → ExternalApi" not in result


def test_filter_baseline_for_topic_preserves_domain_description() -> None:
    baseline = _sample_baseline()
    result = _filter_baseline_for_topic(baseline, {"OrderService"})
    assert "## 支付域" in result
    assert "处理支付与退款的核心业务域。" in result
    assert "## 其他章节" in result
    assert "应完整保留。" in result


def test_working_memory_slice_for_modules() -> None:
    memory = WorkingMemory()
    memory.code_snippets = [
        "[OrderService @ src/Order.java]\ncode1",
        "[PaymentService]\ncode2",
        "[RefundService @ src/Refund.java]\ncode3",
        "unprefixed mention of PaymentService",
    ]
    memory.discovered_call_chains = [
        "OrderService: A → B",
        "Unrelated: X → Y",
    ]
    sliced = memory.slice_for_modules({"OrderService", "PaymentService"})
    assert len(sliced.code_snippets) == 3
    assert any("OrderService" in s for s in sliced.code_snippets)
    assert any("PaymentService" in s for s in sliced.code_snippets)
    assert not any("RefundService" in s for s in sliced.code_snippets)
    assert len(sliced.discovered_call_chains) == 1
    assert sliced.relevant_modules == {"OrderService", "PaymentService"}


def test_slice_empty_modules_returns_empty_memory() -> None:
    memory = WorkingMemory()
    memory.code_snippets = ["[Foo]\ncode"]
    sliced = memory.slice_for_modules(set())
    assert sliced.code_snippets == []
    assert sliced.discovered_call_chains == []


def test_scale_explore_params_large_domain() -> None:
    wiki_cfg = MagicMock()
    wiki_cfg.domain_agent_explore_max_rounds = 8
    wiki_cfg.domain_agent_explore_max_tool_calls = 30
    wiki_cfg.explore_scale_threshold_medium = 20
    wiki_cfg.explore_scale_threshold_large = 40
    rounds, calls = _scale_explore_params(50, wiki_cfg)
    assert rounds == 12
    assert calls == 45


def test_scale_explore_params_small_domain_unchanged() -> None:
    wiki_cfg = MagicMock()
    wiki_cfg.domain_agent_explore_max_rounds = 8
    wiki_cfg.domain_agent_explore_max_tool_calls = 30
    wiki_cfg.explore_scale_threshold_medium = 20
    wiki_cfg.explore_scale_threshold_large = 40
    rounds, calls = _scale_explore_params(10, wiki_cfg)
    assert rounds == 8
    assert calls == 30
