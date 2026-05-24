from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.flow_baseline import (
    EntryPointInfo,
    FlowBaseline,
    extract_flow_baseline,
    format_flow_baseline_for_prompt,
)


class TestExtractFlowBaseline:
    @pytest.mark.asyncio
    async def test_with_entry_points(self):
        mock_graph = AsyncMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"name": "createOrder", "module": "OrderController",
             "file_path": "src/order/controller.py", "annotations": "RequestMapping,PostMapping"},
        ]
        mock_graph.execute_query.return_value = mock_result

        baseline = await extract_flow_baseline(mock_graph, "order", ["OrderController", "OrderService"])
        assert baseline.domain_name == "order"
        assert len(baseline.entry_points) >= 1
        assert baseline.module_count == 2

    @pytest.mark.asyncio
    async def test_no_entry_points(self):
        mock_graph = AsyncMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_graph.execute_query.return_value = mock_result

        baseline = await extract_flow_baseline(mock_graph, "utils", ["StringUtils"])
        assert baseline.entry_points == []

    @pytest.mark.asyncio
    async def test_graph_query_failure(self):
        mock_graph = AsyncMock()
        mock_graph.execute_query.side_effect = Exception("connection error")

        baseline = await extract_flow_baseline(mock_graph, "broken", ["Mod"])
        assert baseline.entry_points == []
        assert baseline.call_chains == []


class TestFormatFlowBaseline:
    def test_format_with_entries(self):
        baseline = FlowBaseline(
            domain_name="order",
            entry_points=[
                EntryPointInfo("createOrder", "OrderController", "http", "src/order/ctrl.py"),
                EntryPointInfo("onPayment", "PaymentListener", "event", "src/pay/listener.py"),
            ],
            call_chains=[],
            module_count=5,
            cross_domain_calls=[("OrderService", "PaymentService")],
        )
        text = format_flow_baseline_for_prompt(baseline)
        assert "OrderController.createOrder" in text
        assert "[http]" in text
        assert "PaymentService" in text

    def test_format_empty(self):
        baseline = FlowBaseline("empty", [], [], 0, [])
        text = format_flow_baseline_for_prompt(baseline)
        assert text == ""
