"""Tests for Batch AE pipeline P3 fixes."""
from __future__ import annotations

import importlib
import sys
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import _maybe_split
from wiki.nodes.classify import detect_reorg_node
from wiki.nodes.tour import generate_tour_node


def _domain_tree_with_modules(count: int) -> list[dict]:
    return [{"name": "root", "modules": [f"mod-{i}" for i in range(count)]}]


def test_maybe_split_wikilinks_include_domain_path() -> None:
    """Split topic wikilinks must be path-qualified with domain slug."""
    sections = ["## 概述\n\n" + "概述内容。" * 200]
    for i in range(5):
        sections.append(f"## 章节{i}\n\n" + f"章节{i}的详细内容。" * 430)
    content = "\n\n".join(sections)

    pages = _maybe_split(content, "large-domain", "大型域")
    parent = pages[0]
    assert "[[large-domain/章节0]]" in parent["content"]
    assert "[[章节0]]" not in parent["content"]


@pytest.mark.asyncio
async def test_detect_reorg_light_at_5_percent() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(100),
        "is_incremental": True,
        "affected_domains": ["payment"],
        "affected_modules": {f"mod-{i}" for i in range(5)},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "light"


@pytest.mark.asyncio
async def test_detect_reorg_medium_at_15_percent() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(100),
        "is_incremental": True,
        "affected_domains": ["payment"],
        "affected_modules": {f"mod-{i}" for i in range(15)},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "medium"


@pytest.mark.asyncio
async def test_detect_reorg_heavy_at_40_percent() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(100),
        "is_incremental": True,
        "affected_domains": ["payment"],
        "affected_modules": {f"mod-{i}" for i in range(40)},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "heavy"


@pytest.mark.asyncio
async def test_detect_reorg_respects_configurable_thresholds() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(100),
        "is_incremental": True,
        "affected_domains": ["payment"],
        "affected_modules": {f"mod-{i}" for i in range(20)},
        "config": {"reorg_light_threshold": 0.05, "reorg_heavy_threshold": 0.25},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "medium"


@pytest.mark.asyncio
async def test_light_reorg_skips_tour_generation() -> None:
    existing_tour = {"total_pages": 3, "steps": [{"title": "Step 1", "pages": []}]}
    state = {
        "reorg_type": "light",
        "guided_tour": existing_tour,
        "pages": [{"path": "/wiki/a", "covered_entity_uids": ["u1"]}],
        "architecture_layers": {},
    }
    with patch("wiki.nodes.tour.build_tour") as mock_build:
        result = await generate_tour_node(state)
    mock_build.assert_not_called()
    assert result["guided_tour"] == existing_tour


def test_pipeline_state_omits_dead_observability_fields() -> None:
    import typing

    from wiki.pipeline_state import WikiPipelineState

    hints = typing.get_type_hints(WikiPipelineState)
    assert "stage_timings" not in hints
    assert "llm_call_count" not in hints


@pytest.mark.asyncio
async def test_mermaid_fix_skipped_when_already_fixed() -> None:
    from wiki.nodes.compose import _sanitize_pages

    page = {
        "content": "```mermaid\ngraph TD\n  A-->B\n```",
        "metadata": {"mermaid_fixed": True},
    }
    mock_llm = AsyncMock()
    with patch(
        "wiki.source_ref_validator.repair_broken_mermaid_blocks",
        new_callable=AsyncMock,
    ) as mock_repair:
        await _sanitize_pages([page], [], [], llm=mock_llm)
    mock_repair.assert_not_called()


@pytest.mark.asyncio
async def test_domain_compose_mermaid_fix_skipped_when_already_fixed() -> None:
    from wiki.nodes.domain_compose import compose_domain_agents_node

    state = {
        "domain_tree": [{"name": "leaf", "modules": ["m1"], "children": []}],
        "modules": {},
        "pages": [],
        "errors": [],
    }
    fixed_page = {
        "path": "/__domains__/leaf/_overview",
        "content": "content",
        "metadata": {"mermaid_fixed": True},
    }

    with patch(
        "wiki.nodes.domain_compose._collect_leaf_domains",
        return_value=[{"name": "leaf", "modules": ["m1"]}],
    ):
        with patch(
            "wiki.nodes.domain_compose.DomainDocAgent",
        ) as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.generate_with_iterations = AsyncMock(return_value=[fixed_page])
            mock_agent_cls.return_value = mock_agent
            with patch(
                "wiki.source_ref_validator.repair_broken_mermaid_blocks",
                new_callable=AsyncMock,
            ) as mock_repair:
                await compose_domain_agents_node(
                    state,
                    {"configurable": {"llm": AsyncMock()}},
                )
    mock_repair.assert_not_called()


def test_deprecated_compose_nodes_not_in_nodes_all() -> None:
    import wiki.nodes as nodes_pkg

    assert "compose_leaf_pages_node" not in nodes_pkg.__all__
    assert "plan_topic_structure_node" not in nodes_pkg.__all__


def test_hybrid_query_imports_without_jieba_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module import must succeed whether jieba is available or not."""
    monkeypatch.delitem(sys.modules, "query.hybrid_query", raising=False)
    monkeypatch.delitem(sys.modules, "jieba", raising=False)

    mod = importlib.import_module("query.hybrid_query")
    assert mod is not None

    monkeypatch.setitem(sys.modules, "jieba", MagicMock())
    importlib.reload(mod)
    assert mod is not None


def test_hybrid_query_cjk_tokenization_when_jieba_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "query.hybrid_query", raising=False)
    monkeypatch.delitem(sys.modules, "jieba", raising=False)
    mod = importlib.import_module("query.hybrid_query")

    ids = mod._extract_identifiers("用户登录刷新会话")
    assert isinstance(ids, list)


@pytest.mark.asyncio
async def test_generate_titles_uses_budget_resolver() -> None:
    from wiki.nodes.graph_nodes import generate_titles_node

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"title": "认证模块", "description": "处理登录"}'
    mock_resolver = MagicMock()
    mock_resolver.resolve.return_value = 777

    state = {
        "business_id": "test",
        "module_tree": [
            {
                "canonical_key": "src-auth",
                "entity_uids": ["u1", "u2"],
                "file_paths": [],
                "title": "",
                "description": "",
                "token_estimate": 0,
                "children": [],
            },
        ],
        "canonical_keys": {"src-auth": ""},
    }
    config = {"configurable": {"llm": mock_llm, "budget_resolver": mock_resolver}}

    with patch("wiki.nodes.graph_nodes.acquire_llm_quota", new_callable=AsyncMock):
        await generate_titles_node(state, config)

    mock_resolver.resolve.assert_called()
    call_args = mock_resolver.resolve.call_args
    assert call_args[0][0] == "title_generation"
    mock_llm.generate.assert_called_once()
    assert mock_llm.generate.call_args.kwargs["max_tokens"] == 777
