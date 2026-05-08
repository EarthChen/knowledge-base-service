"""Tests for P2.2: query_domain_dependencies tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.page_agent import AGENT_TOOLS, ToolResult, WikiPageAgent, WorkingMemory


class TestDomainDepsToolDefinition:
    def test_in_agent_tools(self):
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        assert "query_domain_dependencies" in names

    def test_has_domain_name_param(self):
        for tool in AGENT_TOOLS:
            if tool["function"]["name"] == "query_domain_dependencies":
                params = tool["function"]["parameters"]["properties"]
                assert "domain_name" in params


class TestDomainDepsTool:
    @pytest.mark.asyncio
    async def test_returns_outgoing_deps(self):
        gs = MagicMock()
        gs.execute_query = AsyncMock(side_effect=[
            MagicMock(data=[
                {"target_domain": "Notification", "caller_name": "PayService", "callee_name": "NotifySvc"},
            ]),
            MagicMock(data=[]),  # incoming
        ])
        agent = WikiPageAgent(MagicMock(), gs)
        result = await agent._tool_query_domain_dependencies({"domain_name": "Payment"})
        assert result["domain"] == "Payment"
        assert len(result["outgoing"]) == 1
        assert result["outgoing"][0]["target_domain"] == "Notification"

    @pytest.mark.asyncio
    async def test_returns_incoming_deps(self):
        gs = MagicMock()
        gs.execute_query = AsyncMock(side_effect=[
            MagicMock(data=[]),  # outgoing
            MagicMock(data=[
                {"source_domain": "Order", "caller_name": "OrderSvc", "callee_name": "PaymentGateway"},
            ]),
        ])
        agent = WikiPageAgent(MagicMock(), gs)
        result = await agent._tool_query_domain_dependencies({"domain_name": "Payment"})
        assert len(result["incoming"]) == 1
        assert result["incoming"][0]["source_domain"] == "Order"

    @pytest.mark.asyncio
    async def test_handles_missing_domain_name(self):
        agent = WikiPageAgent(MagicMock(), MagicMock())
        result = await agent._tool_query_domain_dependencies({"domain_name": ""})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_handles_graph_error(self):
        gs = MagicMock()
        gs.execute_query = AsyncMock(side_effect=RuntimeError("db error"))
        agent = WikiPageAgent(MagicMock(), gs)
        result = await agent._tool_query_domain_dependencies({"domain_name": "Payment"})
        # Should not raise, returns empty lists
        assert result["outgoing"] == []
        assert result["incoming"] == []

    @pytest.mark.asyncio
    async def test_limits_results(self):
        gs = MagicMock()
        rows = [{"target_domain": f"Domain{i}", "caller_name": "A", "callee_name": "B"} for i in range(25)]
        gs.execute_query = AsyncMock(side_effect=[
            MagicMock(data=rows),
            MagicMock(data=[]),
        ])
        agent = WikiPageAgent(MagicMock(), gs)
        result = await agent._tool_query_domain_dependencies({"domain_name": "Payment"})
        assert len(result["outgoing"]) <= 15


class TestWorkingMemoryDomainDeps:
    def test_incorporate_outgoing(self):
        mem = WorkingMemory()
        mem.incorporate([ToolResult(tool="query_domain_dependencies", data={
            "domain": "Payment",
            "outgoing": [{"target_domain": "Notification", "via": "PaySvc → NotifySvc"}],
            "incoming": [],
        })])
        assert any("Payment → Notification" in c for c in mem.discovered_call_chains)

    def test_incorporate_incoming(self):
        mem = WorkingMemory()
        mem.incorporate([ToolResult(tool="query_domain_dependencies", data={
            "domain": "Payment",
            "outgoing": [],
            "incoming": [{"source_domain": "Order", "via": "OrderSvc → PayGateway"}],
        })])
        assert any("Order → Payment" in c for c in mem.discovered_callers)
