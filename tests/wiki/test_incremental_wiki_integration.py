"""Integration tests for incremental wiki update parameter flow."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.persistence import WikiPagePersistence


class TestGenerateBusinessWikiIncremental:
    @pytest.mark.asyncio
    async def test_incremental_passes_affected_domains_to_pipeline(self):
        """When incremental=True and domains are affected, pipeline receives affected_domains."""
        from wiki.service import WikiService

        mock_store = AsyncMock()
        mock_wiki_store = AsyncMock()

        svc = WikiService.__new__(WikiService)
        svc._store = mock_store
        svc._wiki_store = mock_wiki_store
        svc._search_service = None
        svc._llm_provider = None
        svc._llm_factory = None
        svc._llm = None
        svc._wiki_cfg = MagicMock(
            business_wiki_skip_repo_pages=True,
            business_repo_concurrency=2,
        )

        mock_graph = MagicMock()
        mock_graph.list_repository_modules = AsyncMock(return_value=[])
        svc._graph = mock_graph

        mock_persistence = MagicMock()
        mock_persistence.cleanup_stale_wiki_pages = AsyncMock(return_value=0)
        mock_persistence.cleanup_stale_domain_edges = AsyncMock()
        mock_persistence.cleanup_stale_domain_sections = AsyncMock()
        svc._persistence = mock_persistence

        mock_tree_linker = MagicMock()
        mock_tree_linker.link_pages_to_tree = AsyncMock()
        mock_tree_linker.link_pages_to_nested_tree = AsyncMock()
        svc._tree_linker = mock_tree_linker

        svc._persist_pages_to_graph = AsyncMock()
        svc._persist_resolved_pipeline_wikilinks = AsyncMock()

        mock_wiki_store.list_indexed_repositories = AsyncMock(
            return_value=[{"repository": "repo1"}],
        )

        mock_wiki_store.get_repo_wiki_freshness = AsyncMock(
            return_value={
                "repo1": {"has_wiki": True, "freshness_pct": 100.0},
            },
        )
        mock_wiki_store.get_pipeline_domain_tree_snapshot = AsyncMock(
            return_value={
                "tree": [{"name": "DomainA", "modules": ["ModA"], "children": []}],
                "review_status": {},
            },
        )
        mock_wiki_store.get_wiki_generation_version = AsyncMock(return_value=1)

        snapshot_tree = [{"name": "DomainA", "modules": ["ModA"], "children": []}]

        mock_diff = MagicMock()
        mock_diff.is_empty = False
        mock_diff.total_changed = 2
        mock_diff.affected_domains = ["DomainA"]

        pipeline_tree = [{"name": "DomainA"}]

        with patch(
            "wiki.service.compute_domain_diff",
            new_callable=AsyncMock,
            return_value=mock_diff,
        ):
            with patch(
                "wiki.pipeline_orchestrator.run_langgraph_pipeline",
                new_callable=AsyncMock,
            ) as mock_pipeline:
                mock_pipeline.return_value = MagicMock(
                    pages=[],
                    errors=[],
                    domain_mapping={},
                    domain_tree=pipeline_tree,
                    review_status=None,
                    resolved_links={},
                )
                mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

                await svc.generate_business_wiki("ultron", incremental=True)

                assert mock_pipeline.await_count == 1
                kwargs = mock_pipeline.call_args.kwargs
                assert kwargs.get("affected_domains") == ["DomainA"]
                assert kwargs.get("existing_domain_tree") == snapshot_tree

    def test_domain_diff_is_empty_when_no_changes(self):
        """DomainDiff with no hash mismatch reports is_empty (pipeline still runs)."""
        from wiki.incremental_diff import DomainDiff

        mock_diff = DomainDiff(
            affected_domains=[],
            changed_module_uids=[],
            total_changed=0,
        )
        assert mock_diff.is_empty is True

    @pytest.mark.asyncio
    async def test_is_incremental_true_when_affected_domains_but_no_skipped_repos(self):
        """Pipeline incremental mode when domain diff fires but every repo is 'changed' (none skipped)."""
        from wiki.service import WikiService

        mock_store = AsyncMock()
        mock_wiki_store = AsyncMock()

        svc = WikiService.__new__(WikiService)
        svc._store = mock_store
        svc._wiki_store = mock_wiki_store
        svc._search_service = None
        svc._llm_provider = None
        svc._llm_factory = None
        svc._llm = None
        svc._wiki_cfg = MagicMock(
            business_wiki_skip_repo_pages=True,
            business_repo_concurrency=2,
        )

        mock_graph = MagicMock()
        mock_graph.list_repository_modules = AsyncMock(
            return_value=[MagicMock(uid="m1", properties={"name": "ModA"})],
        )
        svc._graph = mock_graph

        mock_persistence = MagicMock()
        mock_persistence.cleanup_stale_wiki_pages = AsyncMock(return_value=0)
        mock_persistence.cleanup_stale_domain_edges = AsyncMock()
        mock_persistence.cleanup_stale_domain_sections = AsyncMock()
        svc._persistence = mock_persistence

        mock_tree_linker = MagicMock()
        mock_tree_linker.link_pages_to_tree = AsyncMock()
        mock_tree_linker.link_pages_to_nested_tree = AsyncMock()
        svc._tree_linker = mock_tree_linker

        svc._persist_pages_to_graph = AsyncMock()
        svc._persist_resolved_pipeline_wikilinks = AsyncMock()

        mock_wiki_store.list_indexed_repositories = AsyncMock(
            return_value=[{"repository": "repo1"}],
        )
        mock_wiki_store.get_repo_wiki_freshness = AsyncMock(
            return_value={
                "repo1": {
                    "last_indexed": "2024-01-02T00:00:00",
                    "last_generated": "2024-01-01T00:00:00",
                },
            },
        )
        mock_wiki_store.get_pipeline_domain_tree_snapshot = AsyncMock(
            return_value={"tree": [], "review_status": {}},
        )
        mock_wiki_store.get_wiki_generation_version = AsyncMock(return_value=1)

        mock_diff = MagicMock()
        mock_diff.is_empty = False
        mock_diff.total_changed = 1
        mock_diff.affected_domains = ["DomainA"]

        with patch(
            "wiki.service.compute_domain_diff",
            new_callable=AsyncMock,
            return_value=mock_diff,
        ):
            with patch(
                "wiki.pipeline_orchestrator.run_langgraph_pipeline",
                new_callable=AsyncMock,
            ) as mock_pipeline:
                mock_pipeline.return_value = MagicMock(
                    pages=[],
                    errors=[],
                    domain_mapping={},
                    domain_tree=[],
                    review_status=None,
                    resolved_links={},
                )
                await svc.generate_business_wiki("ultron", incremental=True)

        kwargs = mock_pipeline.call_args.kwargs
        assert kwargs.get("is_incremental") is True
        assert kwargs.get("affected_domains") == ["DomainA"]


class TestIncrementalPersistence:
    @pytest.mark.asyncio
    async def test_cleanup_stale_by_domain_deletes_only_affected(self):
        """Domain-scoped cleanup should only delete pages from affected domains."""
        mock_store = AsyncMock()
        mock_store.execute_query = AsyncMock(
            return_value=MagicMock(data=[{"deleted": 3}]),
        )

        persistence = WikiPagePersistence.__new__(WikiPagePersistence)
        persistence._store = mock_store

        deleted = await persistence.cleanup_stale_wiki_pages_by_domain(
            repository="ultron",
            current_page_paths=["ultron/用户管理"],
            affected_domains=["用户管理"],
        )
        assert deleted >= 0
        call_args = mock_store.execute_query.call_args
        query = call_args[0][0] if call_args[0] else ""
        assert "$domains" in query or "title" in query.lower()

    @pytest.mark.asyncio
    async def test_cleanup_stale_by_domain_empty_domains_is_noop(self):
        """Empty affected_domains should not delete anything."""
        mock_store = AsyncMock()
        persistence = WikiPagePersistence.__new__(WikiPagePersistence)
        persistence._store = mock_store

        deleted = await persistence.cleanup_stale_wiki_pages_by_domain(
            repository="ultron",
            current_page_paths=[],
            affected_domains=[],
        )
        assert deleted == 0
        mock_store.execute_query.assert_not_called()
