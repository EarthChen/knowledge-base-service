"""Tests for method-level call chain builder."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.call_chain_builder import CallChainBuilder, CallChainNode, MethodCallChain


def _mock_graph_store(rows: list[dict]) -> MagicMock:
    result = MagicMock()
    result.data = rows
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=result)
    return gs


class TestCallChainBuilderBasic:
    @pytest.mark.asyncio
    async def test_empty_modules_returns_empty(self):
        gs = _mock_graph_store([])
        builder = CallChainBuilder(gs)
        chains = await builder.build_chains([])
        assert chains == []

    @pytest.mark.asyncio
    async def test_simple_two_step_chain(self):
        rows = [
            {
                "caller_method": "handleRequest",
                "callee_method": "processOrder",
                "caller_module": "OrderController",
                "callee_module": "OrderService",
                "caller_file": "a.java",
                "callee_file": "b.java",
                "caller_sig": "void handleRequest()",
                "callee_sig": "void processOrder()",
            },
            {
                "caller_method": "processOrder",
                "callee_method": "saveOrder",
                "caller_module": "OrderService",
                "callee_module": "OrderDAO",
                "caller_file": "b.java",
                "callee_file": "c.java",
                "caller_sig": "void processOrder()",
                "callee_sig": "void saveOrder()",
            },
        ]
        gs = _mock_graph_store(rows)
        builder = CallChainBuilder(gs)
        chains = await builder.build_chains(["OrderController", "OrderService", "OrderDAO"])
        assert len(chains) >= 1
        longest = max(chains, key=lambda c: c.depth)
        assert longest.depth >= 2
        names = [n.func_name for n in longest.chain]
        assert "handleRequest" in names


class TestCallChainBuilderEdgeCases:
    @pytest.mark.asyncio
    async def test_cycle_prevention(self):
        rows = [
            {
                "caller_method": "a",
                "callee_method": "b",
                "caller_module": "M1",
                "callee_module": "M2",
                "caller_file": "",
                "callee_file": "",
                "caller_sig": "",
                "callee_sig": "",
            },
            {
                "caller_method": "b",
                "callee_method": "a",
                "caller_module": "M2",
                "callee_module": "M1",
                "caller_file": "",
                "callee_file": "",
                "caller_sig": "",
                "callee_sig": "",
            },
        ]
        gs = _mock_graph_store(rows)
        builder = CallChainBuilder(gs)
        chains = await builder.build_chains(["M1", "M2"], max_depth=10)
        for chain in chains:
            assert chain.depth <= 10
            keys = [f"{n.module_name}.{n.func_name}" for n in chain.chain]
            assert len(keys) == len(set(keys)), "cycle detected in chain"

    @pytest.mark.asyncio
    async def test_depth_limit_respected(self):
        gs = _mock_graph_store([
            {
                "caller_method": f"f{i}",
                "callee_method": f"f{i+1}",
                "caller_module": "M",
                "callee_module": "M",
                "caller_file": "",
                "callee_file": "",
                "caller_sig": "",
                "callee_sig": "",
            }
            for i in range(20)
        ])
        builder = CallChainBuilder(gs)
        chains = await builder.build_chains(["M"], max_depth=3)
        for chain in chains:
            assert chain.depth <= 3

    @pytest.mark.asyncio
    async def test_max_chains_limit(self):
        rows = [
            {
                "caller_method": f"entry{i}",
                "callee_method": f"target{i}",
                "caller_module": "M",
                "callee_module": "M",
                "caller_file": "",
                "callee_file": "",
                "caller_sig": "",
                "callee_sig": "",
            }
            for i in range(50)
        ]
        gs = _mock_graph_store(rows)
        builder = CallChainBuilder(gs)
        chains = await builder.build_chains(["M"], max_chains=5)
        assert len(chains) <= 5

    @pytest.mark.asyncio
    async def test_graph_store_failure_returns_empty(self):
        gs = MagicMock()
        gs.execute_query = AsyncMock(side_effect=Exception("db error"))
        builder = CallChainBuilder(gs)
        chains = await builder.build_chains(["M"])
        assert chains == []


class TestFormatForPrompt:
    def test_empty_chains(self):
        builder = CallChainBuilder(MagicMock())
        text = builder.format_for_prompt([])
        assert "无" in text

    def test_formats_chain_nodes(self):
        chains = [
            MethodCallChain(
                entry_method="handleRequest",
                entry_module="Controller",
                chain=[
                    CallChainNode(
                        "handleRequest",
                        "Controller",
                        "a.java",
                        "void handleRequest()",
                    ),
                    CallChainNode(
                        "process",
                        "Service",
                        "b.java",
                        "void process()",
                    ),
                ],
                depth=1,
            ),
        ]
        builder = CallChainBuilder(MagicMock())
        text = builder.format_for_prompt(chains)
        assert "Controller.handleRequest" in text
        assert "Service.process" in text
        assert "→" in text
