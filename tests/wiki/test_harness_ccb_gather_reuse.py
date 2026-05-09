"""Tests: harness gather phase reuses EnrichedDomainContext (CCB) instead of re-querying the graph."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.content_context_builder import (
    EnrichedDomainContext,
    EntityDetail,
    MethodDetail,
)
from wiki.harness import WikiGenerationHarness
from wiki.harness_planner import GenerationPlan, PlannedQuery, SectionPlan


@pytest.mark.asyncio
async def test_gather_skips_graph_when_ccb_has_entity_methods():
    """query_module_detail should use CCB biz ENTITY methods and not call graph_store."""
    mock_agent = AsyncMock()
    mock_llm = AsyncMock()
    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    harness = WikiGenerationHarness(mock_agent, mock_graph, mock_llm)
    plan = GenerationPlan(
        outline=[
            SectionPlan(
                name="概述",
                queries=[
                    PlannedQuery(
                        tool_name="query_module_detail",
                        params={"module_name": "ModA"},
                        target_section="概述",
                        priority=1,
                    ),
                ],
            ),
        ],
    )
    ccb = EnrichedDomainContext(domain_name="Dom", parent_domain="root")
    ccb.biz_entities = [
        EntityDetail(
            uid="u1",
            name="ModA",
            repository="repo",
            file_path="src/ModA.java",
            entity_type="Module",
            business_summary="",
            methods=[
                MethodDetail(
                    name="doThing",
                    signature="(String a): void",
                    file_path="src/ModA.java",
                    start_line=10,
                    repository="repo",
                    docstring="Does thing",
                    module_name="ModA",
                ),
            ],
        ),
    ]

    await harness._gather(plan, ccb)

    mock_graph.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_gather_queries_graph_when_ccb_missing_entity():
    """If CCB does not cover requested modules, fall back to graph_store."""
    mock_agent = AsyncMock()
    mock_llm = AsyncMock()
    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    harness = WikiGenerationHarness(mock_agent, mock_graph, mock_llm)
    plan = GenerationPlan(
        outline=[
            SectionPlan(
                name="概述",
                queries=[
                    PlannedQuery(
                        tool_name="query_module_detail",
                        params={"module_name": "MissingMod"},
                        target_section="概述",
                        priority=1,
                    ),
                ],
            ),
        ],
    )
    ccb = EnrichedDomainContext(domain_name="Dom", parent_domain="root")
    ccb.biz_entities = []

    await harness._gather(plan, ccb)

    mock_graph.execute_query.assert_called()
