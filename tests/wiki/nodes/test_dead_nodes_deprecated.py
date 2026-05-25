"""Tests documenting deprecated compose nodes not wired into the production pipeline."""
from __future__ import annotations

import warnings

import pytest

from wiki.nodes.compose import compose_leaf_pages_node, plan_topic_structure_node
from wiki.pipeline_graph import build_wiki_pipeline


class TestDeadNodesNotInPipeline:
    """Production wiki generation uses compose_domain_agents_node, not the legacy
    topic-structure / leaf-pages compose path.  These functions remain importable
    for unit tests and backward compatibility but are intentionally excluded from
    build_wiki_pipeline()."""

    @pytest.fixture()
    def pipeline_node_names(self) -> set[str]:
        pipeline = build_wiki_pipeline(checkpointer=False)
        return set(pipeline.nodes.keys())

    def test_compose_leaf_pages_not_wired(self, pipeline_node_names: set[str]) -> None:
        assert "compose_leaf_pages" not in pipeline_node_names
        assert "compose_domain_agents" in pipeline_node_names

    def test_plan_topic_structure_not_wired(self, pipeline_node_names: set[str]) -> None:
        assert "plan_topic_structure" not in pipeline_node_names


class TestDeadNodesDeprecated:
    @pytest.mark.asyncio
    async def test_compose_leaf_pages_emits_deprecation(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await compose_leaf_pages_node({}, {"configurable": {}})

        assert any(
            issubclass(w.category, DeprecationWarning)
            and "compose_domain_agents_node" in str(w.message)
            for w in caught
        )

    @pytest.mark.asyncio
    async def test_plan_topic_structure_emits_deprecation(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await plan_topic_structure_node({}, {"configurable": {}})

        assert any(
            issubclass(w.category, DeprecationWarning)
            and "compose_domain_agents_node" in str(w.message)
            for w in caught
        )
