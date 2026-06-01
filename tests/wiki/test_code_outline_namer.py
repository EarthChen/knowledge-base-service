"""Tests for G6 — code outline injection into domain namer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.graph_domain_namer import (
    GraphDomainNamer,
    fetch_code_outline_for_namer,
    format_code_outline,
)


def test_format_code_outline_basic() -> None:
    outlines = {
        "PaymentService": ["processPayment(order)", "validateCard(card)", "refundOrder(id)"],
        "UserService": ["createUser(dto)", "authenticate(creds)"],
    }
    result = format_code_outline(
        outlines,
        module_names=["PaymentService", "UserService"],
    )
    assert "Code outline:" in result
    assert "PaymentService: processPayment(order), validateCard(card), refundOrder(id)" in result
    assert "UserService: createUser(dto), authenticate(creds)" in result


def test_format_code_outline_respects_max_lines() -> None:
    outlines = {f"Mod{i}": [f"method{j}()" for j in range(5)] for i in range(20)}
    module_names = [f"Mod{i}" for i in range(20)]
    result = format_code_outline(
        outlines,
        module_names=module_names,
        max_total_lines=10,
    )
    lines = [line for line in result.splitlines() if line.strip()]
    assert len(lines) <= 10
    assert lines[0] == "Code outline:"


def test_format_code_outline_rank_aware() -> None:
    outlines = {
        "HighRank": ["a()", "b()", "c()", "d()", "e()"],
        "MidRank": ["a()", "b()", "c()", "d()", "e()"],
        "LowRank": ["a()", "b()", "c()", "d()", "e()"],
    }
    ranks = {"HighRank": 1.0, "MidRank": 0.5, "LowRank": 0.0}
    result = format_code_outline(
        outlines,
        module_names=["HighRank", "MidRank", "LowRank"],
        module_ranks=ranks,
        max_methods_per_module=5,
    )
    high_line = next(line for line in result.splitlines() if "HighRank:" in line)
    mid_line = next(line for line in result.splitlines() if "MidRank:" in line)
    low_line = next(line for line in result.splitlines() if "LowRank:" in line)
    assert high_line.count("()") >= 4
    assert 2 <= mid_line.count("()") <= 3
    assert low_line.count("()") == 1


def test_format_code_outline_empty_modules() -> None:
    assert format_code_outline({}, module_names=[]) == ""
    assert format_code_outline({"Foo": []}, module_names=["Foo"]) == ""
    assert format_code_outline({"Foo": ["bar()"]}, module_names=["Unknown"]) == ""


@pytest.mark.asyncio
async def test_fetch_code_outline_for_namer_queries_graph() -> None:
    graph_store = MagicMock()
    graph_store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "module_name": "PaymentService",
                    "func_name": "processPayment",
                    "signature": "processPayment(Order order)",
                },
                {
                    "module_name": "PaymentService",
                    "func_name": "validateCard",
                    "signature": "validateCard(Card card)",
                },
            ],
        ),
    )
    result = await fetch_code_outline_for_namer(graph_store, ["PaymentService"])
    assert "Code outline:" in result
    assert "PaymentService:" in result
    assert "processPayment" in result
    graph_store.execute_query.assert_awaited_once()


class TestNamerOutlineInjection:
    @pytest.mark.asyncio
    async def test_namer_includes_outline_in_prompt(self) -> None:
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value='{"slug": "payment", "display_name": "支付", "description": ""}',
        )
        namer = GraphDomainNamer(
            llm,
            module_outlines={
                "PaymentService": ["processPayment(order)", "validateCard(card)"],
            },
        )
        await namer.name_community(
            module_infos=[{"name": "PaymentService", "path": "pay/PaymentService.java"}],
        )
        prompt = llm.generate.call_args[0][0]
        assert "Code outline:" in prompt
        assert "processPayment(order)" in prompt
        assert "validateCard(card)" in prompt

    @pytest.mark.asyncio
    async def test_namer_works_without_outline(self) -> None:
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value='{"slug": "payment", "display_name": "支付", "description": ""}',
        )
        namer = GraphDomainNamer(llm)
        result = await namer.name_community(
            module_infos=[{"name": "PaymentService", "path": "pay/PaymentService.java"}],
        )
        assert result["slug"] == "payment"
        prompt = llm.generate.call_args[0][0]
        assert "Code outline:" not in prompt
