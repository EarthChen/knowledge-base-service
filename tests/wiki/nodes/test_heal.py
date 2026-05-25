"""Tests for heal node structural check cache deduplication."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest

from wiki.models import ImportanceTier, WikiPage
from wiki.nodes.heal import _page_passes_post_heal
from wiki.quality_evaluator import WikiPageQualityScore, WikiQualityEvaluator


def _make_page(content: str = "# Title\n\n## Overview\n\nBody with enough text.\n") -> WikiPage:
    return WikiPage.from_dict({
        "path": "wiki/test-page",
        "title": "Test",
        "content": content,
        "page_type": "module_overview",
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "structure"},
    })


def _score(overall: float) -> WikiPageQualityScore:
    return WikiPageQualityScore(
        page_path="wiki/test-page",
        completeness=overall,
        helpfulness=overall,
        truthfulness=overall,
        overall=overall,
        issues=[],
    )


@pytest.fixture
def evaluator() -> MagicMock:
    ev = MagicMock(spec=WikiQualityEvaluator)
    ev.structural_check.return_value = _score(0.8)
    return ev


def test_page_passes_post_heal_cache_hit_skips_structural_check(evaluator: MagicMock) -> None:
    page = _make_page()
    content_hash = hashlib.sha256(page.content.encode("utf-8", errors="replace")).hexdigest()
    cache = {
        page.path: {
            "score": {"l1_structural": 0.85},
            "content_hash": content_hash,
        }
    }
    state = {"config": {"importance_tiers": {page.path: ImportanceTier.STANDARD.value}}}

    assert _page_passes_post_heal(page, state, evaluator, check_cache=cache) is True
    evaluator.structural_check.assert_not_called()


def test_page_passes_post_heal_cache_miss_calls_and_caches(evaluator: MagicMock) -> None:
    page = _make_page()
    cache: dict[str, dict] = {}
    state = {"config": {"importance_tiers": {page.path: ImportanceTier.STANDARD.value}}}

    assert _page_passes_post_heal(page, state, evaluator, check_cache=cache) is True
    evaluator.structural_check.assert_called_once_with(page)
    assert page.path in cache
    assert cache[page.path]["score"]["l1_structural"] == 0.8
    assert cache[page.path]["content_hash"] == hashlib.sha256(
        page.content.encode("utf-8", errors="replace")
    ).hexdigest()


def test_page_passes_post_heal_content_change_invalidates_cache(evaluator: MagicMock) -> None:
    page = _make_page("original content")
    old_hash = hashlib.sha256(b"original content").hexdigest()
    cache = {
        page.path: {
            "score": {"l1_structural": 0.9},
            "content_hash": old_hash,
        }
    }
    page.content = "updated content with different hash"
    state = {"config": {"importance_tiers": {page.path: ImportanceTier.STANDARD.value}}}

    _page_passes_post_heal(page, state, evaluator, check_cache=cache)
    evaluator.structural_check.assert_called_once()
