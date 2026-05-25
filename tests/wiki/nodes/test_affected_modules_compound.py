"""Tests for compound-key affected_modules (J-5)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.nodes.graph_domain_decompose import (
    _assign_changed_modules_incremental,
    graph_driven_domain_decompose_node,
)

_LONG = "A detailed module summary. " * 5  # >= 100 chars to skip round 2


def _make_module_dict(repo_id: str, name: str, uid: str = "") -> dict:
    return {
        "uid": uid or f"Module::{repo_id}::{name}:0",
        "label": "Module",
        "properties": {
            "name": name,
            "path": f"{repo_id}/src/{name}.java",
            "repository": repo_id,
        },
    }


class TestServiceCompoundAffectedModules:
    @pytest.mark.asyncio
    async def test_service_builds_compound_affected_modules(self) -> None:
        """service.py passes repo|name compound keys to the pipeline."""
        from wiki.service import WikiService

        uid_a = "uid-repo-a-userservice"
        mod_a = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "UserService"},
            uid=uid_a,
        )
        mod_b = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "UserService"},
            uid="uid-repo-b-userservice",
        )

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
        svc._budget_resolver = None

        mock_graph = MagicMock()
        mock_graph.list_repository_modules = AsyncMock(
            side_effect=lambda repo: {
                "repo-a": [mod_a],
                "repo-b": [mod_b],
            }.get(repo, []),
        )
        svc._graph = mock_graph

        mock_persistence = MagicMock()
        mock_persistence.cleanup_stale_wiki_pages = AsyncMock(return_value=0)
        mock_persistence.cleanup_stale_wiki_pages_by_domain = AsyncMock(return_value=0)
        mock_persistence.cleanup_stale_domain_edges = AsyncMock()
        mock_persistence.cleanup_stale_domain_sections = AsyncMock()
        mock_persistence.list_pinned_modules = AsyncMock(return_value=[])
        svc._persistence = mock_persistence

        mock_tree_linker = MagicMock()
        mock_tree_linker.link_pages_to_tree = AsyncMock()
        mock_tree_linker.link_pages_to_nested_tree = AsyncMock()
        svc._tree_linker = mock_tree_linker

        svc._persist_pages_to_graph = AsyncMock()
        svc._persist_resolved_pipeline_wikilinks = AsyncMock()

        mock_wiki_store.list_indexed_repositories = AsyncMock(
            return_value=[
                {"repository": "repo-a"},
                {"repository": "repo-b"},
            ],
        )
        mock_wiki_store.get_repo_wiki_freshness = AsyncMock(
            return_value={
                "repo-a": {"has_wiki": True, "freshness_pct": 100.0},
                "repo-b": {"has_wiki": True, "freshness_pct": 100.0},
            },
        )
        mock_wiki_store.get_pipeline_domain_tree_snapshot = AsyncMock(
            return_value={"tree": [], "review_status": {}},
        )
        mock_wiki_store.get_wiki_generation_version = AsyncMock(return_value=1)

        mock_diff = MagicMock()
        mock_diff.is_empty = False
        mock_diff.total_changed = 1
        mock_diff.affected_domains = ["user-domain"]
        mock_diff.changed_module_uids = [uid_a]

        with patch(
            "wiki.incremental_diff.compute_domain_diff",
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
                mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

                await svc.generate_business_wiki("test-biz", incremental=True)

                kwargs = mock_pipeline.call_args.kwargs
                assert kwargs.get("affected_modules") == ["repo-a|UserService"]


class TestComposeCompoundAffectedModules:
    @pytest.mark.asyncio
    async def test_compound_affected_only_resummarizes_matching_repo(self) -> None:
        """compose with repo-a|UserService affected does not re-summarize repo-b's UserService."""
        from wiki.nodes.compose import compose_leaf_modules_node

        state = {
            "modules": {
                "repo-a": [
                    {
                        "properties": {"name": "UserService", "path": "repo-a/user.py"},
                        "labels": ["Module"],
                    },
                ],
                "repo-b": [
                    {
                        "properties": {"name": "UserService", "path": "repo-b/user.py"},
                        "labels": ["Module"],
                    },
                ],
            },
            "entity_roles": {},
            "is_incremental": True,
            "affected_modules": {"repo-a|UserService"},
            "module_summaries": {
                "UserService": {"summary_text": _LONG + " shared old", "key_methods": []},
                "repo-a|UserService": {"summary_text": _LONG + " repo-a old", "key_methods": []},
                "repo-b|UserService": {
                    "summary_text": _LONG + " repo-b unchanged",
                    "key_methods": [],
                },
            },
        }

        summarized_repos: list[str] = []

        async def mock_gen(name, mod_list, *args, **kwargs):
            summarized_repos.extend(d.get("_repo", "") for d in mod_list)
            return (
                name,
                {"summary_text": _LONG + " new repo-a summary", "key_methods": []},
            )

        configurable = {"llm": AsyncMock(), "graph_store": None}

        with patch(
            "wiki.nodes.compose._generate_single_module_summary",
            side_effect=mock_gen,
        ):
            with patch("wiki.nodes.compose.PipelineConcurrency") as mock_pc:
                mock_pc.semaphore.return_value = MagicMock(
                    __aenter__=AsyncMock(),
                    __aexit__=AsyncMock(),
                )
                result = await compose_leaf_modules_node(state, {"configurable": configurable})

        assert summarized_repos == ["repo-a"]
        summaries = result.get("module_summaries", {})
        assert summaries["repo-b|UserService"]["summary_text"] == _LONG + " repo-b unchanged"


class TestGraphDecomposeCompoundAffectedModules:
    @pytest.mark.asyncio
    async def test_compound_affected_modules_identifies_only_changed_repo(self) -> None:
        """Incremental decompose treats only the matching repo|name as changed."""
        modules = {
            "repo-a": [_make_module_dict("repo-a", "UserService", "uid-a")],
            "repo-b": [_make_module_dict("repo-b", "UserService", "uid-b")],
        }
        existing_mapping = {
            "user-domain": [
                ("repo-a", "UserService"),
                ("repo-b", "UserService"),
            ],
        }
        state = {
            "business_id": "test-biz",
            "repositories": ["repo-a", "repo-b"],
            "modules": modules,
            "entity_roles": {
                "uid-a": "has_business_logic",
                "uid-b": "has_business_logic",
            },
            "is_incremental": True,
            "existing_domain_mapping": existing_mapping,
            "affected_modules": ["repo-a|UserService"],
            "pinned_modules": {},
            "domain_tree": [
                {"name": "user-domain", "modules": ["UserService"], "children": []},
            ],
            "domain_mapping": {},
            "affected_domains": [],
        }

        captured_changed: list[tuple[str, str]] = []
        original_assign = _assign_changed_modules_incremental

        def spy_assign(changed_biz, *args, **kwargs):
            captured_changed.extend(changed_biz)
            return original_assign(changed_biz, *args, **kwargs)

        mock_graph_store = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}

        with patch(
            "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
            new_callable=AsyncMock,
            return_value=([], []),
        ), patch(
            "wiki.nodes.graph_domain_decompose._assign_changed_modules_incremental",
            side_effect=spy_assign,
        ):
            await graph_driven_domain_decompose_node(state, config)

        assert captured_changed == [("repo-a", "UserService")]
