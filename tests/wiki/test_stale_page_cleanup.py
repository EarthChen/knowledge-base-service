from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class TestStalePageCleanup:
    @pytest.mark.asyncio
    async def test_stale_pages_deleted(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        store = AsyncMock()
        store.query = AsyncMock(
            side_effect=[
                [
                    {"path": "/__domains__/old-domain/_overview", "uid": "uid1"},
                    {"path": "/__domains__/current-domain/_overview", "uid": "uid2"},
                    {"path": "/__domains__/old-domain/topic1/_topic", "uid": "uid3"},
                ],
                None,
                None,
            ]
        )
        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = store

        deleted = await runner._cleanup_stale_domain_pages(
            business_id="ultron",
            current_domain_slugs={"current-domain"},
        )
        assert deleted == 2

    @pytest.mark.asyncio
    async def test_no_stale_pages(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        store = AsyncMock()
        store.query = AsyncMock(
            return_value=[
                {"path": "/__domains__/current/_overview", "uid": "uid1"},
            ]
        )
        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = store

        deleted = await runner._cleanup_stale_domain_pages(
            business_id="test",
            current_domain_slugs={"current"},
        )
        assert deleted == 0


def _nested_domain_tree():
    from wiki.dependency_graph import DomainNode

    return [
        DomainNode(
            name="family",
            children=[
                DomainNode(name="family-core-operations", modules=["mod-a"]),
                DomainNode(
                    name="family-other",
                    children=[DomainNode(name="nested-child")],
                ),
            ],
        ),
    ]


class TestAllTreeSlugs:
    def test_all_tree_slugs_collects_nested_names(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        slugs = BusinessPipelineRunner._all_tree_slugs(_nested_domain_tree())
        assert slugs == {
            "family",
            "family-core-operations",
            "family-other",
            "nested-child",
        }

    def test_all_tree_slugs_empty_tree(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        assert BusinessPipelineRunner._all_tree_slugs([]) == set()


class TestStaleCleanupWithNestedTree:
    @pytest.mark.asyncio
    async def test_stale_cleanup_with_nested_tree_slugs(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        store = AsyncMock()
        store.query = AsyncMock(
            side_effect=[
                [
                    {
                        "path": "/__domains__/family-core-operations/topic1/_topic",
                        "uid": "uid-nested",
                    },
                    {"path": "/__domains__/stale-domain/_overview", "uid": "uid-stale"},
                ],
                None,
            ]
        )
        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = store

        domain_mapping = {"family": []}
        all_active_slugs = set(domain_mapping.keys())
        all_active_slugs |= BusinessPipelineRunner._all_tree_slugs(_nested_domain_tree())

        deleted = await runner._cleanup_stale_domain_pages(
            business_id="ultron",
            current_domain_slugs=all_active_slugs,
        )
        assert deleted == 1
        stale_calls = [c for c in store.query.call_args_list if "SET wp.stale = true" in str(c)]
        assert len(stale_calls) == 1
        assert stale_calls[0][0][1]["uid"] == "uid-stale"


class TestContainerDomainSlugs:
    def test_get_container_slugs(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner
        from wiki.dependency_graph import DomainNode

        tree = [
            DomainNode(
                name="domain-01",
                children=[DomainNode(name="child-a", modules=["m1"])],
            ),
            DomainNode(name="leaf-domain", modules=["m2"]),
        ]
        slugs = BusinessPipelineRunner._get_container_slugs(tree)
        assert slugs == {"domain-01"}

    def test_get_container_slugs_leaf_domain_excluded(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner
        from wiki.dependency_graph import DomainNode

        tree = [DomainNode(name="leaf-only", modules=["mod-x"])]
        assert BusinessPipelineRunner._get_container_slugs(tree) == set()


class TestContainerDomainTopicCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_container_domain_topics(self):
        from wiki.business_pipeline_runner import BusinessPipelineRunner
        from wiki.dependency_graph import DomainNode

        store = AsyncMock()
        store.query = AsyncMock(
            side_effect=[
                [{"cnt": 5}],
                [{"cnt": 0}],
            ]
        )
        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = store

        tree = [
            DomainNode(
                name="domain-01",
                children=[DomainNode(name="child-a", modules=["m1"])],
            ),
            DomainNode(
                name="closed-friend-relations",
                children=[DomainNode(name="sub", modules=["m2"])],
            ),
        ]
        deleted = await runner._cleanup_container_domain_topics("ultron", tree)
        assert deleted == 5
        assert store.query.await_count == 2
        prefixes = [c[0][1]["prefix"] for c in store.query.call_args_list]
        assert "/__domains__/domain-01/" in prefixes
        assert "/__domains__/closed-friend-relations/" in prefixes
