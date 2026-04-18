"""P2 cross-module integration tests — real wiki stack with mocked graph + LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from llm.base_provider import BaseLLMProvider, GatewayLLMProviderAdapter, LLMPortBridge
from llm.provider_factory import LLMProviderFactory, ProviderConfig
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.ask import WikiAskService
from wiki.cache import WikiCache
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData, WikiDataCollector
from wiki.disk_exporter import WikiDiskExporter
from wiki.exporter import WikiExporter
from wiki.incremental import WikiIncrementalUpdater
from wiki.models import PageType, SourceLocation, WikiConfig, WikiPage, WikiPageMetadata
from wiki.persistent_cache import WikiPersistentCache
from wiki.repo_composer import WikiRepoComposer
from wiki.search import SearchResponse, SearchResult, WikiSearchService
from wiki.service import WikiService

REPO = "demo-repo"


def _module(uid: str, path: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.MODULE,
        properties={"path": path, "name": path.strip("/").split("/")[-1]},
        uid=uid,
    )


def _class_node(uid: str, name: str, file_path: str, module_uid: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS,
        properties={
            "name": name,
            "file": file_path,
            "start_line": 1,
            "end_line": 20,
            "fqn": f"demo.{name}",
            "module_uid": module_uid,
            "module_path": "pkg/a" if "a/" in file_path or "/a/" in file_path else "pkg/b",
        },
        uid=uid,
    )


def _function(uid: str, name: str, file_path: str, module_uid: str, fqn: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.FUNCTION,
        properties={
            "name": name,
            "file": file_path,
            "start_line": 10,
            "end_line": 30,
            "fqn": fqn,
            "module_uid": module_uid,
        },
        uid=uid,
    )


def _page_data(repo: str, node: GraphNode) -> PageData:
    fp = str(node.properties.get("file") or node.properties.get("path") or "")
    return PageData(
        node=node,
        edges=[],
        children=[],
        source_location=SourceLocation(
            file_path=fp or "x.py",
            start_line=1,
            end_line=2,
            fqn=str(node.properties.get("fqn") or node.uid),
            repository=repo,
        ),
        method_locations=[],
        business_summary=None,
        methods=[],
    )


def _make_full_graph(
    *,
    with_classes: bool = False,
    with_call_flow: bool = False,
) -> AsyncMock:
    """Graph mock implementing repo composer, data collector, incremental, and service ports."""
    m_a = _module("mod_a", "pkg/a")
    m_b = _module("mod_b", "pkg/b")
    cls_a = _class_node("cls_a", "Alpha", "src/a/A.java", "mod_a")
    cls_b = _class_node("cls_b", "Beta", "src/b/B.java", "mod_b")

    fn_e = _function("fn_e", "entry", "pkg/a/handler.py", "mod_a", "demo.entry")
    fn_c = _function("fn_c", "callee", "pkg/a/service.py", "mod_a", "demo.callee")

    version = {"n": 10}

    g = AsyncMock()
    g.find_edges = AsyncMock(return_value=[])
    g.find_node_by_uid = AsyncMock(return_value=None)
    g.find_node_by_fqn = AsyncMock(return_value=None)
    g.list_repository_modules = AsyncMock(return_value=[m_a, m_b])
    g.find_top_level_modules = AsyncMock(return_value=[m_a, m_b])

    imp = [GraphEdge(EdgeType.IMPORTS, m_b.uid, m_a.uid, {})]
    g.find_module_import_edges = AsyncMock(return_value=imp)

    calls: list[GraphEdge] = []
    if with_call_flow:
        calls = [GraphEdge(EdgeType.CALLS, fn_e.uid, fn_c.uid, {})]
    g.find_repository_calls_edges = AsyncMock(return_value=calls)

    async def find_children(repo: str, parent_uid: str) -> list[GraphNode]:
        if parent_uid == m_a.uid:
            if with_call_flow:
                return [fn_e, fn_c]
            if with_classes:
                return [cls_a]
            return []
        if parent_uid == m_b.uid:
            if with_classes:
                return [cls_b]
            return []
        return []

    g.find_children = AsyncMock(side_effect=find_children)

    async def find_node_by_path(repo: str, path: str) -> GraphNode | None:
        if path in ("pkg/a", "pkg/a/"):
            return m_a
        if path in ("pkg/b", "pkg/b/"):
            return m_b
        return None

    g.find_node_by_path = AsyncMock(side_effect=find_node_by_path)

    async def find_nodes_by_file(repo: str, fp: str) -> list[GraphNode]:
        if fp == "src/a/A.java":
            return [cls_a]
        if fp == "src/b/B.java":
            return [cls_b]
        return []

    g.find_nodes_by_file = AsyncMock(side_effect=find_nodes_by_file)
    g.find_neighbors = AsyncMock(return_value=[])
    g.get_graph_version = AsyncMock(side_effect=lambda _r: version["n"])

    async def bump(_r: str) -> int:
        version["n"] += 1
        return version["n"]

    g.increment_graph_version = AsyncMock(side_effect=bump)

    return g


def _repo_composer_from_graph(graph: AsyncMock, llm_port: Any | None = None) -> WikiRepoComposer:
    collector = WikiDataCollector(graph)
    llm = llm_port
    composer = WikiComposer(llm, WikiContextBuilder(llm))
    return WikiRepoComposer(
        graph=graph,
        composer=composer,
        collector=collector,
        exporter=WikiExporter(),
        context_builder=WikiContextBuilder(llm),
    )


@pytest.fixture
def wiki_config() -> WikiConfig:
    return WikiConfig(repository=REPO, mode="structure", format="json", language="en")


@pytest.mark.asyncio
async def test_full_repo_compose_with_export(tmp_path: Path, wiki_config: WikiConfig) -> None:
    graph = _make_full_graph()
    rc = _repo_composer_from_graph(graph)
    pages, structure = await rc.compose_repo_wiki(REPO, wiki_config)

    exporter = WikiDiskExporter(WikiExporter())
    result = exporter.export_to_disk(pages, structure, str(tmp_path))

    assert result.index_path
    assert Path(result.index_path).is_file()
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) >= 2
    index_text = Path(result.index_path).read_text(encoding="utf-8")
    assert REPO in index_text
    assert "Contents" in index_text


@pytest.mark.asyncio
async def test_full_repo_compose_with_cache(tmp_path: Path, wiki_config: WikiConfig) -> None:
    graph = _make_full_graph()
    rc = _repo_composer_from_graph(graph)
    pages, _structure = await rc.compose_repo_wiki(REPO, wiki_config)

    mem = WikiCache(max_size=50)
    pc = WikiPersistentCache(mem, cache_dir=str(tmp_path / "cache"))
    pc.put(REPO, "repo", wiki_config.mode, 42, pages)
    loaded = pc.get(REPO, "repo", wiki_config.mode, 42)
    assert loaded is not None
    assert [p.path for p in loaded] == [p.path for p in pages]


@pytest.mark.asyncio
async def test_incremental_update_invalidates_cache(tmp_path: Path, wiki_config: WikiConfig) -> None:
    graph = _make_full_graph(with_classes=True)
    mem = WikiCache(max_size=50)
    pc = WikiPersistentCache(mem, cache_dir=str(tmp_path / "cache"))
    dummy = WikiPage(
        path="modules/x.md",
        title="x",
        page_type=PageType.MODULE_OVERVIEW,
        content="hold",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0, generation_mode="structure", fallback_tier=3),
    )
    pc.put(REPO, "repo", wiki_config.mode, 99, [dummy])
    assert pc.get(REPO, "repo", wiki_config.mode, 99) is not None

    collector = WikiDataCollector(graph)
    composer = WikiComposer(None, WikiContextBuilder(None))
    updater = WikiIncrementalUpdater(graph, composer, collector, WikiContextBuilder(None), pc)

    await updater.update_from_diff(
        REPO,
        [("M", "src/a/A.java", "src/a/A.java")],
        wiki_config,
        previous_glossary={},
    )
    assert pc.get(REPO, "repo", wiki_config.mode, 99) is None


@pytest.mark.asyncio
async def test_provider_factory_with_wiki_service() -> None:
    inner = MagicMock()
    inner.complete = AsyncMock(return_value="Synthetic module documentation paragraph.")
    inner.close = AsyncMock()
    gw = GatewayLLMProviderAdapter(inner)
    factory = LLMProviderFactory(ProviderConfig(default_provider="gateway"), gateway_provider=gw)

    m_a = _module("mod_a", "pkg/a")
    graph = AsyncMock()
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_uid = AsyncMock(return_value=None)
    graph.find_node_by_path = AsyncMock(return_value=m_a)
    graph.find_node_by_fqn = AsyncMock(return_value=None)
    graph.find_children = AsyncMock(return_value=[])
    graph.find_top_level_modules = AsyncMock(return_value=[])
    graph.list_repository_modules = AsyncMock(return_value=[])

    svc = WikiService(graph=graph, llm=None, repository_exists=AsyncMock(return_value=True), llm_factory=factory)
    bundle = await svc.generate(
        REPO,
        "module:pkg/a",
        mode="full",
        format="json",
    )
    assert "pages" in bundle
    assert bundle["pages"]
    inner.complete.assert_awaited()


@pytest.mark.asyncio
async def test_incremental_preserves_unchanged(wiki_config: WikiConfig) -> None:
    graph = _make_full_graph(with_classes=True)
    rc = _repo_composer_from_graph(graph)
    pages_before, _ = await rc.compose_repo_wiki(REPO, wiki_config)
    by_path = {p.path: p.content for p in pages_before}
    b_path = "modules/pkg_b.md"
    assert b_path in by_path

    collector = WikiDataCollector(graph)
    composer = WikiComposer(None, WikiContextBuilder(None))
    cache = WikiCache()
    updater = WikiIncrementalUpdater(graph, composer, collector, WikiContextBuilder(None), cache)
    res = await updater.update_from_diff(
        REPO,
        [("M", "src/a/A.java", "src/a/A.java")],
        wiki_config,
        previous_glossary={},
    )
    assert b_path not in res.affected_pages

    pages_after, _ = await rc.compose_repo_wiki(REPO, wiki_config)
    after_map = {p.path: p.content for p in pages_after}
    assert after_map[b_path] == by_path[b_path]


@pytest.mark.asyncio
async def test_repo_composer_uses_page_templates(wiki_config: WikiConfig) -> None:
    graph = _make_full_graph()
    rc = _repo_composer_from_graph(graph)
    pages, _ = await rc.compose_repo_wiki(REPO, wiki_config)
    arch = next(p for p in pages if p.page_type == PageType.ARCHITECTURE)
    assert "architecture/overview.md" in arch.path
    assert "Architecture" in arch.content or "layer" in arch.content.lower()


@pytest.mark.asyncio
async def test_repo_composer_generates_data_flows(wiki_config: WikiConfig) -> None:
    graph = _make_full_graph(with_call_flow=True)
    rc = _repo_composer_from_graph(graph)
    pages, _ = await rc.compose_repo_wiki(REPO, wiki_config)
    flows = [p for p in pages if p.page_type == PageType.DATA_FLOW]
    assert flows
    assert any("Data flow" in p.title or "Flow" in p.title for p in flows)
    assert all(p.path.startswith("flows/") for p in flows)


@pytest.mark.asyncio
async def test_incremental_after_full_compose(wiki_config: WikiConfig) -> None:
    graph = _make_full_graph(with_classes=True)
    rc = _repo_composer_from_graph(graph)
    await rc.compose_repo_wiki(REPO, wiki_config)

    collector = WikiDataCollector(graph)
    composer = WikiComposer(None, WikiContextBuilder(None))
    updater = WikiIncrementalUpdater(graph, composer, collector, WikiContextBuilder(None), WikiCache())

    res = await updater.update_from_diff(
        REPO,
        [("M", "src/a/A.java", "src/a/A.java")],
        wiki_config,
        previous_glossary={"Alpha": "term"},
    )
    assert "classes/Alpha.md" in res.affected_pages
    assert res.graph_version >= 11


@pytest.mark.asyncio
async def test_factory_fallback_chain_integration() -> None:
    req = httpx.Request("GET", "https://example.invalid/v1/chat")
    resp = httpx.Response(503, request=req)
    err = httpx.HTTPStatusError("upstream", request=req, response=resp)

    primary = MagicMock(spec=BaseLLMProvider)
    primary.complete = AsyncMock(side_effect=err)
    primary.close = AsyncMock()

    fallback = MagicMock(spec=BaseLLMProvider)
    fallback.complete = AsyncMock(return_value="fallback-ok")
    fallback.close = AsyncMock()

    cfg = ProviderConfig(default_provider="primary", fallback_provider="fallback")
    factory = LLMProviderFactory(cfg)
    factory._providers["primary"] = primary  # noqa: SLF001
    factory._providers["fallback"] = fallback  # noqa: SLF001

    out = await factory.complete_with_fallback([{"role": "user", "content": "ping"}])
    assert out == "fallback-ok"
    fallback.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_bridge_with_composer(wiki_config: WikiConfig) -> None:
    prov = MagicMock(spec=BaseLLMProvider)
    prov.complete = AsyncMock(return_value="Bridged LLM narrative.")
    bridge = LLMPortBridge(prov)

    m_a = _module("mod_a", "pkg/a")
    graph = AsyncMock()
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_uid = AsyncMock(return_value=None)
    graph.find_children = AsyncMock(return_value=[])

    collector = WikiDataCollector(graph)

    async def collect(_repo: str, node: GraphNode) -> PageData:
        return _page_data(_repo, node)

    collector.collect = AsyncMock(side_effect=collect)

    composer = WikiComposer(bridge, WikiContextBuilder(bridge))
    full_cfg = WikiConfig(repository=REPO, mode="full", format="json", language="en")
    page = await composer.compose_page(
        await collector.collect(REPO, m_a),
        PageType.MODULE_OVERVIEW,
        full_cfg,
    )
    assert "Bridged LLM narrative" in page.content
    prov.complete.assert_awaited()


@pytest.mark.asyncio
async def test_persistent_cache_roundtrip_with_real_pages(tmp_path: Path, wiki_config: WikiConfig) -> None:
    graph = _make_full_graph()
    rc = _repo_composer_from_graph(graph)
    pages, _ = await rc.compose_repo_wiki(REPO, wiki_config)

    mem = WikiCache()
    pc = WikiPersistentCache(mem, cache_dir=str(tmp_path / "pc"))
    pc.put(REPO, "repo", wiki_config.mode, 3, pages)
    got = pc.get(REPO, "repo", wiki_config.mode, 3)
    assert got is not None
    assert len(got) == len(pages)
    assert {p.title for p in got} == {p.title for p in pages}


@pytest.mark.asyncio
async def test_disk_export_with_cross_refs(tmp_path: Path, wiki_config: WikiConfig) -> None:
    graph = _make_full_graph()
    rc = _repo_composer_from_graph(graph)
    pages, structure = await rc.compose_repo_wiki(REPO, wiki_config)

    exporter = WikiDiskExporter(WikiExporter())
    exporter.export_to_disk(pages, structure, str(tmp_path))

    linked_any = False
    for md in tmp_path.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        if "](" in text and ".md" in text:
            linked_any = True
            break
    assert linked_any


@pytest.mark.asyncio
async def test_p1_wiki_generate_still_works() -> None:
    m_a = _module("mod_a", "pkg/a")
    graph = AsyncMock()
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_uid = AsyncMock(return_value=None)
    graph.find_node_by_path = AsyncMock(return_value=m_a)
    graph.find_node_by_fqn = AsyncMock(return_value=None)
    graph.find_children = AsyncMock(return_value=[])
    graph.find_top_level_modules = AsyncMock(return_value=[])
    graph.list_repository_modules = AsyncMock(return_value=[])

    svc = WikiService(graph=graph, llm=None, repository_exists=AsyncMock(return_value=True))
    bundle = await svc.generate(REPO, "module:pkg/a", mode="structure", format="json")
    assert bundle["pages"]
    assert not bundle.get("degraded", True)


@pytest.mark.asyncio
async def test_p1_search_still_works() -> None:
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[{"page_path": "classes/Foo.md", "title": "Foo", "snippet": "hello", "source_locations": []}]
        )
    )
    vector = AsyncMock()
    vector.search_all = AsyncMock(return_value=[])
    fts = AsyncMock()
    fts.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    svc = WikiSearchService(graph, vector, fts)
    resp = await svc.search(REPO, "FooService authentication", mode="hybrid", limit=5)
    assert isinstance(resp, SearchResponse)
    assert resp.total >= 0


@pytest.mark.asyncio
async def test_p1_ask_still_works() -> None:
    search = MagicMock()
    search.search = AsyncMock(
        return_value=SearchResponse(
            results=[
                SearchResult(
                    page_path="classes/X.md",
                    title="X",
                    score=0.5,
                    snippet="text",
                    source_locations=[],
                    context={},
                )
            ],
            query_expansion={"original": "q", "expanded_queries": [], "terms": []},
            total=1,
        )
    )
    llm = MagicMock()
    llm.complete = AsyncMock(return_value="Answer text.")

    ask_svc = WikiAskService(search, llm)
    answer = await ask_svc.ask(REPO, "What is X?", mode="hybrid")
    assert "Answer" in answer.content
    llm.complete.assert_awaited()
