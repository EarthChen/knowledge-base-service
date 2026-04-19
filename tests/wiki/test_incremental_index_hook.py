"""P3 — Incremental wiki update hook (update_from_index_event + indexer wiring)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.cache import WikiCache
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData, WikiDataCollector
from wiki.incremental import IncrementalUpdateResult, WikiIncrementalUpdater
from wiki.models import SourceLocation, WikiConfig


def _cls(uid: str, name: str, file_path: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS,
        properties={
            "name": name,
            "file": file_path,
            "start_line": 1,
            "end_line": 10,
            "fqn": f"x.{name}",
        },
        uid=uid,
    )


def _page_data(node: GraphNode) -> PageData:
    return PageData(
        node=node,
        edges=[],
        children=[],
        source_location=SourceLocation(
            file_path=str(node.properties.get("file") or ""),
            start_line=1,
            end_line=2,
            fqn=str(node.properties.get("fqn") or ""),
            repository="r1",
        ),
        method_locations=[],
        business_summary=None,
        methods=[],
    )


@pytest.fixture
def wiki_config() -> WikiConfig:
    return WikiConfig(repository="r1", mode="structure", format="markdown", language="en")


@pytest.mark.asyncio
async def test_update_from_index_event_delegates_to_update_from_diff(wiki_config: WikiConfig) -> None:
    node_a = _cls("uA", "Alpha", "src/A.java")
    graph = AsyncMock()
    graph.get_graph_version = AsyncMock(return_value=5)
    graph.increment_graph_version = AsyncMock(return_value=6)
    graph.find_nodes_by_file = AsyncMock(return_value=[node_a])
    graph.find_neighbors = AsyncMock(return_value=[])

    collector = AsyncMock()
    collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

    cache = WikiCache()
    composer = WikiComposer(None, WikiContextBuilder(None))
    updater = WikiIncrementalUpdater(
        graph, composer, collector, WikiContextBuilder(None), cache,
    )

    spy_calls: list[dict] = []

    async def wrapped_diff(
        self,
        repository: str,
        changed_files: list[tuple[str, str | None, str | None]],
        config: WikiConfig,
        *,
        previous_glossary: dict[str, str] | None = None,
    ) -> IncrementalUpdateResult:
        spy_calls.append(
            {
                "repository": repository,
                "changed_files": changed_files,
                "previous_glossary": previous_glossary,
            },
        )
        return await WikiIncrementalUpdater.update_from_diff(
            self, repository, changed_files, config, previous_glossary=previous_glossary,
        )

    updater.update_from_diff = wrapped_diff.__get__(updater, WikiIncrementalUpdater)  # type: ignore[method-assign]

    cf = [("M", "src/A.java", "src/A.java")]
    res = await updater.update_from_index_event("r1", cf, wiki_config)
    assert len(spy_calls) == 1
    assert spy_calls[0]["repository"] == "r1"
    assert spy_calls[0]["changed_files"] == cf
    assert res.affected_pages == ["classes/Alpha.md"]


@pytest.mark.asyncio
async def test_update_from_index_event_auto_fetches_previous_glossary(wiki_config: WikiConfig) -> None:
    node_a = _cls("uA", "Alpha", "src/A.java")
    graph = AsyncMock()
    graph.get_graph_version = AsyncMock(return_value=1)
    graph.increment_graph_version = AsyncMock(return_value=2)
    graph.find_nodes_by_file = AsyncMock(return_value=[node_a])
    graph.find_neighbors = AsyncMock(return_value=[])

    collector = AsyncMock()
    collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

    cache = WikiCache()
    cache.set_glossary("r1", {"term_a": "definition a"})

    composer = WikiComposer(None, WikiContextBuilder(None))
    updater = WikiIncrementalUpdater(
        graph, composer, collector, WikiContextBuilder(None), cache,
    )

    captured: dict[str, dict[str, str] | None] = {}

    async def capture_glossary(
        self,
        repository: str,
        changed_files: list[tuple[str, str | None, str | None]],
        config: WikiConfig,
        *,
        previous_glossary: dict[str, str] | None = None,
    ) -> IncrementalUpdateResult:
        captured["previous_glossary"] = previous_glossary
        return await WikiIncrementalUpdater.update_from_diff(
            self, repository, changed_files, config, previous_glossary=previous_glossary,
        )

    updater.update_from_diff = capture_glossary.__get__(updater, WikiIncrementalUpdater)  # type: ignore[method-assign]

    await updater.update_from_index_event("r1", [("M", "src/A.java", "src/A.java")], wiki_config)
    assert captured["previous_glossary"] == {"term_a": "definition a"}


@pytest.mark.asyncio
async def test_update_from_index_event_updates_index_and_overview_when_affected(
    wiki_config: WikiConfig,
) -> None:
    node_a = _cls("uA", "Alpha", "src/A.java")
    graph = AsyncMock()
    graph.get_graph_version = AsyncMock(return_value=1)
    graph.increment_graph_version = AsyncMock(return_value=2)
    graph.find_nodes_by_file = AsyncMock(return_value=[node_a])
    graph.find_neighbors = AsyncMock(return_value=[])

    collector = AsyncMock()
    collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

    cache = WikiCache()
    composer = WikiComposer(None, WikiContextBuilder(None))
    updater = WikiIncrementalUpdater(
        graph, composer, collector, WikiContextBuilder(None), cache,
    )

    await updater.update_from_index_event("r1", [("M", "src/A.java", "src/A.java")], wiki_config)

    aux = cache.get_auxiliary_pages("r1")
    paths = {p.path for p in aux}
    assert "index.md" in paths
    assert "overview.md" in paths
    by_path = {p.path: p for p in aux}
    assert "classes/Alpha.md" in by_path["index.md"].content
    assert "graph version" in by_path["overview.md"].content.lower()


@pytest.mark.asyncio
async def test_update_from_index_event_appends_update_log_when_affected(wiki_config: WikiConfig) -> None:
    node_a = _cls("uA", "Alpha", "src/A.java")
    graph = AsyncMock()
    graph.get_graph_version = AsyncMock(return_value=1)
    graph.increment_graph_version = AsyncMock(return_value=2)
    graph.find_nodes_by_file = AsyncMock(return_value=[node_a])
    graph.find_neighbors = AsyncMock(return_value=[])

    collector = AsyncMock()
    collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

    cache = WikiCache()
    composer = WikiComposer(None, WikiContextBuilder(None))
    updater = WikiIncrementalUpdater(
        graph, composer, collector, WikiContextBuilder(None), cache,
    )

    await updater.update_from_index_event("r1", [("M", "src/A.java", "src/A.java")], wiki_config)

    log_text = cache.get_wiki_update_log("r1")
    assert "classes/Alpha.md" in log_text
    assert "graph_version=2" in log_text


@pytest.mark.asyncio
async def test_update_from_index_event_skips_index_log_when_no_affected_pages(
    wiki_config: WikiConfig,
) -> None:
    graph = AsyncMock()
    graph.get_graph_version = AsyncMock(return_value=7)
    graph.increment_graph_version = AsyncMock(return_value=8)
    graph.find_nodes_by_file = AsyncMock(return_value=[])
    graph.find_neighbors = AsyncMock(return_value=[])

    collector = AsyncMock()
    cache = WikiCache()
    updater = WikiIncrementalUpdater(
        graph,
        WikiComposer(None, WikiContextBuilder(None)),
        collector,
        WikiContextBuilder(None),
        cache,
    )

    res = await updater.update_from_index_event(
        "r1",
        [("M", "src/OnlyNeighbors.java", "src/OnlyNeighbors.java")],
        wiki_config,
    )
    assert res.affected_pages == []
    assert cache.get_auxiliary_pages("r1") == []
    assert cache.get_wiki_update_log("r1") == ""


@pytest.mark.asyncio
async def test_incremental_indexer_respects_auto_update_on_index_false() -> None:
    from indexer.incremental_indexer import IncrementalIndexer

    store = AsyncMock()
    builder = MagicMock()
    embed = MagicMock()
    wiki_updater = AsyncMock()

    indexer = IncrementalIndexer(
        store=store,
        graph_builder=builder,
        embedding_gen=embed,
        wiki_incremental_updater=wiki_updater,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = False

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    wiki_updater.update_from_index_event.assert_not_called()


@pytest.mark.asyncio
async def test_incremental_indexer_triggers_wiki_when_auto_update_true() -> None:
    from indexer.incremental_indexer import IncrementalIndexer

    store = AsyncMock()
    builder = MagicMock()
    embed = MagicMock()
    wiki_updater = AsyncMock()

    indexer = IncrementalIndexer(
        store=store,
        graph_builder=builder,
        embedding_gen=embed,
        wiki_incremental_updater=wiki_updater,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = True

    cfg = WikiConfig(repository="my-repo", mode="structure", format="markdown", language="en")

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "pkg/hi.py", "pkg/hi.py")],
            "my-repo",
            wiki_config=cfg,
        )

    wiki_updater.update_from_index_event.assert_awaited_once()
    args, kwargs = wiki_updater.update_from_index_event.call_args
    assert args[0] == "my-repo"
    assert args[1] == [("M", "pkg/hi.py", "pkg/hi.py")]
    assert args[2] is cfg


@pytest.mark.asyncio
async def test_cache_without_glossary_methods_uses_none_previous_glossary(wiki_config: WikiConfig) -> None:
    """Caches that do not implement glossary API behave like previous_glossary=None."""

    class MinimalCache:
        def invalidate(self, repository: str) -> int:
            return 0

    node_a = _cls("uA", "Alpha", "src/A.java")
    graph = AsyncMock()
    graph.get_graph_version = AsyncMock(return_value=1)
    graph.increment_graph_version = AsyncMock(return_value=2)
    graph.find_nodes_by_file = AsyncMock(return_value=[node_a])
    graph.find_neighbors = AsyncMock(return_value=[])

    collector = AsyncMock()
    collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

    captured: dict[str, dict[str, str] | None] = {}

    composer = WikiComposer(None, WikiContextBuilder(None))
    updater = WikiIncrementalUpdater(
        graph, composer, collector, WikiContextBuilder(None), MinimalCache(),  # type: ignore[arg-type]
    )

    async def capture_glossary(
        self,
        repository: str,
        changed_files: list[tuple[str, str | None, str | None]],
        config: WikiConfig,
        *,
        previous_glossary: dict[str, str] | None = None,
    ) -> IncrementalUpdateResult:
        captured["previous_glossary"] = previous_glossary
        return await WikiIncrementalUpdater.update_from_diff(
            self, repository, changed_files, config, previous_glossary=previous_glossary,
        )

    updater.update_from_diff = capture_glossary.__get__(updater, WikiIncrementalUpdater)  # type: ignore[method-assign]

    await updater.update_from_index_event("r1", [("M", "src/A.java", "src/A.java")], wiki_config)
    assert captured["previous_glossary"] is None
