from __future__ import annotations

import pytest
from wiki.flow_baseline import FlowBaseline, EntryPointInfo, format_flow_baseline_for_prompt


class TestDomainComposeFlowBaseline:
    def test_format_injected_into_prompt(self):
        baseline = FlowBaseline(
            "order",
            [EntryPointInfo("create", "Ctrl", "http", "f.py")],
            [],
            3,
            [("OrderService", "PaymentService")],
        )
        text = format_flow_baseline_for_prompt(baseline)
        assert "[http]" in text
        assert "Ctrl.create" in text
        assert "PaymentService" in text
