"""Phase 1 integration: _compose_all_pages wires WikiLinkCache, SKELETON dispatch, and tier pass-through."""

from __future__ import annotations

from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.models import ImportanceTier, PageType, SkeletonStrategy, WikiConfig, WikiStructure, WikiStructureNode
from wiki.service import WikiService
from tests.wiki_config_inject import inject_wiki_embedding, wiki_service_injection


def _graph_base() -> AsyncMock:
    graph = AsyncMock()
    graph.find_modules = AsyncMock(return_value=[])
    graph.find_children = AsyncMock(return_value=[])
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_fqn = AsyncMock(return_value=None)
    graph.find_all_referrers_batch = AsyncMock(return_value={})
    graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    return graph


def _mock_graph_module_overview(uid: str = "Module:test:TestModule") -> AsyncMock:
    graph = _graph_base()
    graph.find_node_by_path = AsyncMock(
        return_value=MagicMock(
            uid=uid,
            label=NodeLabel.MODULE,
            properties={"name": "TestModule", "path": "test_module"},
        )
    )
    return graph


@pytest.mark.asyncio
async def test_compose_all_pages_warms_cache_and_registers_pages() -> None:
    graph = _mock_graph_module_overview()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        **wiki_service_injection(),
    )
    composer = WikiComposer(
        llm=None,
        context_builder=WikiContextBuilder(None),
        store=graph,
    )
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="test_module",
                    title="TestModule",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")

    with patch("wiki.service.WikiLinkCache") as mock_wlc_class:
        cache_instance = MagicMock()
        cache_instance.warm_up = AsyncMock(return_value=2)
        cache_instance.register = MagicMock()
        mock_wlc_class.return_value = cache_instance

        pages, _ = await svc._compose_all_pages("test-repo", structure, config, composer)

    mock_wlc_class.assert_called_once()
    cache_instance.warm_up.assert_awaited_once_with(composer._wiki_store, "test-repo")
    assert composer._wikilink_cache is cache_instance
    assert len(pages) == 2
    mod = next(p for p in pages if p.page_type == PageType.MODULE_OVERVIEW)
    cache_instance.register.assert_any_call(mod.title, mod.path)


@pytest.mark.asyncio
async def test_compose_all_pages_skeleton_skip_returns_no_page() -> None:
    graph = _mock_graph_module_overview()
    w, e = inject_wiki_embedding()
    wiki = w.model_copy(update={"skeleton_strategy": "skip"})
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_config=wiki,
        embedding_config=e,
    )
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="test_module",
                    title="TestModule",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")
    tiers = {"Module:test:TestModule": ImportanceTier.SKELETON}

    pages, _ = await svc._compose_all_pages(
        "test-repo", structure, config, composer, tiers, None,
    )

    assert len(pages) == 1
    assert pages[0].page_type == PageType.REPO_OVERVIEW


@pytest.mark.asyncio
async def test_compose_all_pages_skeleton_skip_still_composes_children() -> None:
    graph = _graph_base()

    async def find_node_by_path(repo: str, path: str) -> MagicMock:
        if path == "parent_mod":
            name = "ParentMod"
        elif path == "parent_mod/child_mod":
            name = "ChildMod"
        else:
            name = path.split("/")[-1] if "/" in path else path
        return MagicMock(
            uid=f"Module:test:{path}",
            label=NodeLabel.MODULE,
            properties={"name": name, "path": path},
        )

    graph.find_node_by_path = AsyncMock(side_effect=find_node_by_path)
    w, e = inject_wiki_embedding()
    wiki = w.model_copy(update={"skeleton_strategy": "skip"})
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_config=wiki,
        embedding_config=e,
    )
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="parent_mod",
                    title="ParentMod",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[
                        WikiStructureNode(
                            path="parent_mod/child_mod",
                            title="ChildMod",
                            page_type=PageType.MODULE_OVERVIEW,
                            children=[],
                        ),
                    ],
                ),
            ],
        ),
        total_pages=3,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")
    tiers = {
        "Module:test:parent_mod": ImportanceTier.SKELETON,
        "Module:test:parent_mod/child_mod": ImportanceTier.STANDARD,
    }

    pages, _ = await svc._compose_all_pages(
        "test-repo", structure, config, composer, tiers, None,
    )

    mod_pages = [p for p in pages if p.page_type == PageType.MODULE_OVERVIEW]
    assert len(mod_pages) == 1
    assert mod_pages[0].title == "ChildMod"
    assert len(pages) == 2


@pytest.mark.asyncio
async def test_compose_all_pages_wikilink_cache_disabled_no_register() -> None:
    graph = _mock_graph_module_overview()
    w, e = inject_wiki_embedding()
    wiki = w.model_copy(update={"wikilink_cache_enabled": False})
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_config=wiki,
        embedding_config=e,
    )
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="test_module",
                    title="TestModule",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")

    with patch("wiki.service.WikiLinkCache") as mock_wlc_class:
        cache_instance = MagicMock()
        cache_instance.warm_up = AsyncMock(return_value=2)
        cache_instance.register = MagicMock()
        mock_wlc_class.return_value = cache_instance

        pages, _ = await svc._compose_all_pages("test-repo", structure, config, composer)

    mock_wlc_class.assert_called_once()
    cache_instance.warm_up.assert_not_called()
    cache_instance.register.assert_not_called()
    assert composer._wikilink_cache is None
    assert len(pages) == 2


@pytest.mark.asyncio
async def test_compose_all_pages_skeleton_template_uses_fallback() -> None:
    graph = _mock_graph_module_overview()
    w, e = inject_wiki_embedding()
    wiki = w.model_copy(update={"skeleton_strategy": "template"})
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_config=wiki,
        embedding_config=e,
    )
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    real_compose = composer.compose_page
    recorded: list[dict[str, object]] = []

    async def tracking_compose(*args: object, **kwargs: object) -> object:
        recorded.append(
            {
                "importance_tier": kwargs.get("importance_tier"),
                "skeleton_strategy": kwargs.get("skeleton_strategy"),
            }
        )
        return await real_compose(*args, **kwargs)

    composer.compose_page = tracking_compose  # type: ignore[method-assign]

    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="test_module",
                    title="TestModule",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")
    tiers = {"Module:test:TestModule": ImportanceTier.SKELETON}

    await svc._compose_all_pages("test-repo", structure, config, composer, tiers, None)

    assert len(recorded) == 1
    assert recorded[0]["importance_tier"] == ImportanceTier.SKELETON
    assert recorded[0]["skeleton_strategy"] == SkeletonStrategy.TEMPLATE


@pytest.mark.asyncio
async def test_compose_all_pages_passes_tier_to_compose_page() -> None:
    graph = _graph_base()

    async def find_node_by_path(repo: str, path: str) -> MagicMock:
        name = path.split("/")[-1] if "/" in path else path
        return MagicMock(
            uid=f"Module:test:{path}",
            label=NodeLabel.MODULE,
            properties={"name": name, "path": path},
        )

    graph.find_node_by_path = AsyncMock(side_effect=find_node_by_path)
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        **wiki_service_injection(),
    )
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    real_compose = composer.compose_page
    tiers_seen: list[ImportanceTier | None] = []

    async def capture_tier(*args: object, **kwargs: object) -> object:
        tiers_seen.append(kwargs.get("importance_tier"))  # type: ignore[arg-type]
        return await real_compose(*args, **kwargs)

    composer.compose_page = capture_tier  # type: ignore[method-assign]

    structure = WikiStructure(
        repository="tr",
        root=WikiStructureNode(
            path=".",
            title="tr",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="m_core", title="m_core", page_type=PageType.MODULE_OVERVIEW, children=[]
                ),
                WikiStructureNode(
                    path="m_std", title="m_std", page_type=PageType.MODULE_OVERVIEW, children=[]
                ),
                WikiStructureNode(
                    path="m_skel",
                    title="m_skel",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=4,
    )
    config = WikiConfig(repository="tr", mode="structure", format="json")
    importance = {
        "Module:test:m_core": ImportanceTier.CORE,
        "Module:test:m_std": ImportanceTier.STANDARD,
        "Module:test:m_skel": ImportanceTier.SKELETON,
    }

    await svc._compose_all_pages("tr", structure, config, composer, importance, None)

    assert Counter(tiers_seen) == Counter(
        [ImportanceTier.CORE, ImportanceTier.STANDARD, ImportanceTier.SKELETON],
    )
