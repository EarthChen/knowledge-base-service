"""Tests for wiki.cot_generator — P4 two-step CoT wiki generation."""

from __future__ import annotations

from typing import Any

import pytest

from wiki.cot_generator import CoTAnalysis, CoTWikiGenerator
from wiki.models import PageType, WikiPageMetadata


class RecordingCompleteLLM:
    """Tracks ``model`` and returns queued string bodies for ``complete``."""

    def __init__(self, bodies: list[str]) -> None:
        self.bodies = list(bodies)
        self.models: list[str | None] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        self.models.append(model)
        if not self.bodies:
            return "{}"
        return self.bodies.pop(0)


def _analysis_json() -> str:
    return (
        '{"core_responsibilities":["auth","sessions"],'
        '"key_interactions":[{"from":"api","to":"db","note":"reads users"}],'
        '"contradictions":[{"topic":"ttl","detail":"doc says 5m code 10m"}],'
        '"structure_suggestions":["add diagram"],'
        '"review_items":[{"id":"r1","question":"Confirm cache key"}]}'
    )


def _pages_json() -> str:
    return (
        '{"pages":['
        '{"path":"docs/scope.md","title":"Scope","page_type":"architecture","content":"# Scope\\n\\nBody."}'
        "]}"
    )


@pytest.mark.asyncio
async def test_step1_produces_valid_cot_analysis_structure() -> None:
    llm = RecordingCompleteLLM([_analysis_json(), _pages_json()])
    gen = CoTWikiGenerator(
        llm,
        analysis_model="fast-model",
        generation_model="big-model",
        cot_enabled=True,
    )
    result = await gen.generate_with_cot("def foo(): pass", existing_wiki="", scope_name="svc")

    assert isinstance(result.analysis, CoTAnalysis)
    assert result.analysis.core_responsibilities == ["auth", "sessions"]
    assert result.analysis.key_interactions == [{"from": "api", "to": "db", "note": "reads users"}]
    assert result.analysis.structure_suggestions == ["add diagram"]


@pytest.mark.asyncio
async def test_step2_generates_wiki_page_objects() -> None:
    llm = RecordingCompleteLLM([_analysis_json(), _pages_json()])
    gen = CoTWikiGenerator(llm, cot_enabled=True)
    result = await gen.generate_with_cot("code", scope_name="svc")

    assert len(result.pages) == 1
    page = result.pages[0]
    assert page.path == "docs/scope.md"
    assert page.title == "Scope"
    assert page.page_type == PageType.ARCHITECTURE
    assert "Body." in page.content


@pytest.mark.asyncio
async def test_contradictions_and_review_items_extracted() -> None:
    llm = RecordingCompleteLLM([_analysis_json(), _pages_json()])
    gen = CoTWikiGenerator(llm, cot_enabled=True)
    result = await gen.generate_with_cot("x")

    assert result.contradictions == [{"topic": "ttl", "detail": "doc says 5m code 10m"}]
    assert result.review_items == [{"id": "r1", "question": "Confirm cache key"}]
    assert result.analysis.contradictions == result.contradictions


@pytest.mark.asyncio
async def test_no_llm_returns_empty_gracefully() -> None:
    gen = CoTWikiGenerator(None, cot_enabled=True)
    result = await gen.generate_with_cot("any")

    assert result.pages == []
    assert result.analysis == CoTAnalysis()
    assert result.contradictions == []
    assert result.review_items == []


@pytest.mark.asyncio
async def test_cot_disabled_not_invoked() -> None:
    llm = RecordingCompleteLLM([_analysis_json(), _pages_json()])
    gen = CoTWikiGenerator(llm, cot_enabled=False)
    result = await gen.generate_with_cot("any")

    assert llm.models == []
    assert result.pages == []
    assert result.analysis == CoTAnalysis()


@pytest.mark.asyncio
async def test_review_needed_markers_when_review_items_exist() -> None:
    llm = RecordingCompleteLLM([_analysis_json(), _pages_json()])
    gen = CoTWikiGenerator(llm, cot_enabled=True)
    result = await gen.generate_with_cot("x")

    assert any("[REVIEW_NEEDED]" in p.content for p in result.pages)


@pytest.mark.asyncio
async def test_different_models_for_analysis_vs_generation() -> None:
    llm = RecordingCompleteLLM([_analysis_json(), _pages_json()])
    gen = CoTWikiGenerator(
        llm,
        analysis_model="analysis-only",
        generation_model="generation-only",
        cot_enabled=True,
    )
    await gen.generate_with_cot("code")

    assert llm.models == ["analysis-only", "generation-only"]


@pytest.mark.asyncio
async def test_invalid_analysis_json_yields_empty_analysis_and_no_pages() -> None:
    llm = RecordingCompleteLLM(["not json at all"])
    gen = CoTWikiGenerator(llm, cot_enabled=True)
    result = await gen.generate_with_cot("x")

    assert result.analysis == CoTAnalysis()
    assert result.pages == []


@pytest.mark.asyncio
async def test_settings_wiki_config_defaults_disable_cot() -> None:
    from config import WikiConfig, get_settings

    w = get_settings().wiki
    assert isinstance(w, WikiConfig)
    assert w.cot_enabled is False
