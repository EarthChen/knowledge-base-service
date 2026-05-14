"""Business wiki generation syncs wiki_code_hash after persisting pipeline pages."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.models import PageType, WikiPage, WikiPageMetadata


def _minimal_wiki_page() -> WikiPage:
    return WikiPage(
        path="stub/domain_stub.md",
        title="Stub",
        page_type=PageType.DOMAIN_OVERVIEW,
        content="# Stub",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.mark.asyncio
async def test_generate_business_wiki_bulk_sets_wiki_code_hashes_per_repo():
    """After persisting business pages, each indexed repo gets wiki_code_hash baseline sync."""
    from wiki.service import WikiService

    mock_store = AsyncMock()
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[
            {"repository": "repo-a"},
            {"repository": "repo-b"},
        ],
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()

    svc = WikiService.__new__(WikiService)
    svc._store = mock_store
    svc._wiki_store = mock_wiki_store
    svc._search_service = None
    svc._llm_provider = None
    svc._llm_factory = None
    svc._llm = MagicMock()
    svc._wiki_cfg = MagicMock(
        business_wiki_skip_repo_pages=True,
        business_repo_concurrency=2,
    )

    mock_graph = MagicMock()

    async def _list_modules(repo: str):
        return [
            MagicMock(
                uid=f"{repo}-mod",
                properties={"name": "Mod"},
                label="Module",
            ),
        ]

    mock_graph.list_repository_modules = AsyncMock(side_effect=_list_modules)
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
    svc._bulk_set_wiki_code_hashes = AsyncMock()

    stub_page = _minimal_wiki_page()

    mock_dep_instance = MagicMock()
    mock_dep_instance.build = AsyncMock(
        return_value=MagicMock(modules=[], edges=[], entry_points=[]),
    )

    mock_related = MagicMock()
    mock_related.build_and_persist = AsyncMock()

    with patch(
        "wiki.pipeline_orchestrator.run_langgraph_pipeline",
        new_callable=AsyncMock,
    ) as mock_pipeline:
        mock_pipeline.return_value = MagicMock(
            pages=[stub_page],
            errors=[],
            domain_mapping={},
            domain_tree=[],
            review_status=None,
            resolved_links={},
            domain_display_names={},
        )
        with patch(
            "wiki.dependency_graph.ModuleDependencyGraph",
            return_value=mock_dep_instance,
        ):
            with patch(
                "wiki.related_pages_builder.RelatedPagesBuilder",
                return_value=mock_related,
            ):
                with patch(
                    "wiki.reference_generator.WikiReferenceGenerator",
                ) as mock_ref_cls:
                    mock_ref_cls.return_value.generate = AsyncMock(return_value=0)
                    await svc.generate_business_wiki(
                        "biz-test",
                        incremental=False,
                    )

    svc._bulk_set_wiki_code_hashes.assert_awaited()
    repos_called = [c.args[0] for c in svc._bulk_set_wiki_code_hashes.call_args_list]
    assert repos_called == ["repo-a", "repo-b"]
