from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from store.falkordb_store import QueryResultWrapper
from wiki.content_context_builder import (
    CallChainStep,
    ContentContextBuilder,
    EnrichedDomainContext,
    MethodDetail,
)


def _graph_execute_factory(rows_by_pattern: dict[str, list[dict]]):
    """Return async execute_query that dispatches by query substring."""

    async def execute_query(cypher: str, params: dict | None = None):
        for needle, rows in rows_by_pattern.items():
            if needle in cypher:
                return QueryResultWrapper(data=list(rows), raw=[])
        return QueryResultWrapper(data=[], raw=[])

    return execute_query


@pytest.mark.asyncio
async def test_build_context_returns_enriched_domain_context():
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        side_effect=_graph_execute_factory({
            "CONTAINS*1..3": [
                {
                    "module_name": "PaymentSvc",
                    "func_name": "pay",
                    "signature": "def pay(self, amount: int) -> bool",
                    "file_path": "pay.py",
                    "start_line": 10,
                    "repository": "repo-a",
                    "docstring": "Process payment.",
                },
            ],
            "CALLS*1..": [
                {"caller": "PaymentSvc", "callee": "UserSvc"},
                {"caller": "PaymentSvc", "callee": "LedgerSvc"},
            ],
            "c:Enum": [
                {"name": "Status", "file": "types.py", "labels": ["Enum"]},
            ],
        }),
    )
    wiki = AsyncMock()
    wiki.execute_query = AsyncMock(
        return_value=QueryResultWrapper(
            data=[{
                "title": "Payment Overview",
                "executive_summary": "Existing payment wiki summary.",
                "content_head": "",
            }],
            raw=[],
        ),
    )

    module_index = {
        "PaymentSvc": [
            {
                "uid": "u-pay",
                "properties": {
                    "name": "PaymentSvc",
                    "file": "pay.py",
                    "business_summary": "Payments module.",
                },
                "_repo": "repo-a",
            },
        ],
    }
    entity_roles = {"u-pay": "has_business_logic"}
    domain_mapping = {
        "payment": [("repo-a", "PaymentSvc")],
        "user": [("repo-a", "UserSvc")],
        "ledger": [("repo-a", "LedgerSvc")],
    }

    builder = ContentContextBuilder(graph, wiki_store=wiki)
    ctx = await builder.build_context(
        domain_name="payment",
        module_names=["PaymentSvc"],
        module_index=module_index,
        entity_roles=entity_roles,
        domain_mapping=domain_mapping,
        depth=2,
    )

    assert isinstance(ctx, EnrichedDomainContext)
    assert ctx.domain_name == "payment"
    assert len(ctx.biz_entities) == 1
    assert "Existing payment wiki summary." in ctx.existing_wiki_context
    assert "Payment Overview" in ctx.existing_wiki_context
    assert len(ctx.enums_and_constants) == 1
    assert ctx.enums_and_constants[0]["name"] == "Status"
    assert "user" in ctx.sibling_domains


@pytest.mark.asyncio
async def test_methods_attached_to_entities():
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        side_effect=_graph_execute_factory({
            "CONTAINS*1..3": [
                {
                    "module_name": "OrderMod",
                    "func_name": "place_order",
                    "signature": "place_order() -> None",
                    "file_path": "order.py",
                    "start_line": 3,
                    "repository": "r1",
                    "docstring": "",
                },
            ],
        }),
    )
    builder = ContentContextBuilder(graph, wiki_store=None)
    ctx = await builder.build_context(
        domain_name="orders",
        module_names=["OrderMod"],
        module_index={
            "OrderMod": [
                {
                    "uid": "e1",
                    "properties": {"name": "OrderMod", "business_summary": "Orders"},
                    "_repo": "r1",
                },
            ],
        },
        entity_roles={"e1": "entry_point"},
        domain_mapping={"orders": [("r1", "OrderMod")]},
    )
    ent = ctx.biz_entities[0]
    assert len(ent.methods) == 1
    assert ent.methods[0].name == "place_order"
    assert ent.methods[0].signature == "place_order() -> None"
    assert isinstance(ent.methods[0], MethodDetail)


@pytest.mark.asyncio
async def test_intra_vs_cross_domain_calls():
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        side_effect=_graph_execute_factory({
            "CONTAINS*1..3": [],
            "CALLS*1..": [
                {"caller": "A", "callee": "B"},
                {"caller": "A", "callee": "Ext"},
            ],
        }),
    )
    builder = ContentContextBuilder(graph, wiki_store=None)
    ctx = await builder.build_context(
        domain_name="d1",
        module_names=["A", "B"],
        module_index={
            "A": [{"uid": "ua", "properties": {"business_summary": "a"}, "_repo": "r"}],
            "B": [{"uid": "ub", "properties": {"business_summary": "b"}, "_repo": "r"}],
        },
        entity_roles={"ua": "has_business_logic", "ub": "has_business_logic"},
        domain_mapping={
            "d1": [("r", "A"), ("r", "B")],
            "other": [("r", "Ext")],
        },
    )

    assert len(ctx.intra_domain_calls) == 1
    assert ctx.intra_domain_calls[0] == CallChainStep(
        caller="A",
        callee="B",
        caller_method="",
        callee_method="",
        relationship="CALLS",
    )
    assert len(ctx.cross_domain_calls) == 1
    assert ctx.cross_domain_calls[0].callee == "Ext"
    assert ctx.dependent_domains == ["other"]
    assert ctx.dependee_domains == []


@pytest.mark.asyncio
async def test_parent_domain_and_sub_topics_passthrough():
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        side_effect=_graph_execute_factory({"CONTAINS*1..3": [], "CALLS*1..": []}),
    )
    builder = ContentContextBuilder(graph, wiki_store=None)
    topics = [{"title": "Subtopic A", "description": "desc", "entity_count": 3}]
    ctx = await builder.build_context(
        domain_name="d1",
        module_names=["M"],
        module_index={"M": [{"uid": "u1", "properties": {"business_summary": "m"}, "_repo": "r"}]},
        entity_roles={"u1": "has_business_logic"},
        domain_mapping={"d1": [("r", "M")]},
        parent_domain="commerce",
        sub_topics=topics,
    )
    assert ctx.parent_domain == "commerce"
    assert ctx.sub_topics == topics


@pytest.mark.asyncio
async def test_wiki_context_fallback_to_content_head():
    """When executive_summary is empty, fallback to first paragraph of content."""
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        side_effect=_graph_execute_factory({"CONTAINS*1..3": [], "CALLS*1..": []}),
    )
    wiki = AsyncMock()
    wiki.execute_query = AsyncMock(
        return_value=QueryResultWrapper(
            data=[{
                "title": "Order Page",
                "executive_summary": "",
                "content_head": "# Orders\n\nThis module handles all order processing logic.\n\nMore details here.",
            }],
            raw=[],
        ),
    )
    builder = ContentContextBuilder(graph, wiki_store=wiki)
    ctx = await builder.build_context(
        domain_name="orders",
        module_names=["M"],
        module_index={"M": [{"uid": "u1", "properties": {"business_summary": "m"}, "_repo": "r"}]},
        entity_roles={"u1": "has_business_logic"},
        domain_mapping={"orders": [("r", "M")]},
    )
    assert "Order Page" in ctx.existing_wiki_context
    assert "# Orders" in ctx.existing_wiki_context


@pytest.mark.asyncio
async def test_wiki_query_failure_returns_empty_context():
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        side_effect=_graph_execute_factory({"CONTAINS*1..3": [], "CALLS*1..": []}),
    )
    wiki = AsyncMock()
    wiki.execute_query = AsyncMock(side_effect=RuntimeError("wiki db down"))
    builder = ContentContextBuilder(graph, wiki_store=wiki)
    ctx = await builder.build_context(
        domain_name="x",
        module_names=["M"],
        module_index={"M": [{"uid": "u1", "properties": {"business_summary": "m"}, "_repo": "r"}]},
        entity_roles={"u1": "has_business_logic"},
        domain_mapping={"x": [("r", "M")]},
    )
    assert ctx.existing_wiki_context == ""


@pytest.mark.asyncio
async def test_key_snippets_populated():
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        side_effect=_graph_execute_factory({
            "CONTAINS*1..3": [],
            "CALLS*1..": [],
            "code_snippet": [
                {"func_name": "handle_pay", "snippet": "def handle_pay(): pass", "file_path": "pay.py", "start_line": 5},
            ],
        }),
    )
    builder = ContentContextBuilder(graph, wiki_store=None)
    ctx = await builder.build_context(
        domain_name="pay",
        module_names=["PaySvc"],
        module_index={"PaySvc": [{"uid": "u1", "properties": {"business_summary": "p"}, "_repo": "r"}]},
        entity_roles={"u1": "has_business_logic"},
        domain_mapping={"pay": [("r", "PaySvc")]},
    )
    assert len(ctx.key_snippets) == 1
    assert "handle_pay" in ctx.key_snippets[0]


@pytest.mark.asyncio
async def test_graph_query_failure_handled():
    async def fail_methods(cypher: str, params: dict | None = None):
        if "CONTAINS*1..3" in cypher:
            raise RuntimeError("graph unavailable")
        if ":CALLS*" in cypher:
            return QueryResultWrapper(data=[], raw=[])
        if "c:Enum" in cypher:
            return QueryResultWrapper(data=[], raw=[])
        return QueryResultWrapper(data=[], raw=[])

    graph = AsyncMock()
    graph.execute_query = AsyncMock(side_effect=fail_methods)

    builder = ContentContextBuilder(graph, wiki_store=None)
    ctx = await builder.build_context(
        domain_name="x",
        module_names=["M"],
        module_index={
            "M": [{"uid": "um", "properties": {"business_summary": "m"}, "_repo": ""}],
        },
        entity_roles={"um": "has_business_logic"},
        domain_mapping={"x": [("", "M")]},
    )

    assert isinstance(ctx, EnrichedDomainContext)
    assert ctx.biz_entities and not ctx.biz_entities[0].methods
    assert ctx.enums_and_constants == []
    assert ctx.intra_domain_calls == []
