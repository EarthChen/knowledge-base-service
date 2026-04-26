"""Tests for wiki.contradiction_detector."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.contradiction_detector import (
    ContradictionDetector,
    ContradictionRecord,
    cosine_similarity,
    group_pages_by_entity_name,
)


def test_group_pages_by_title() -> None:
    rows = [
        {"path": "a.md", "title": "Foo", "content": "x", "referenced_entity_uids": []},
        {"path": "b.md", "title": "Foo", "content": "y", "referenced_entity_uids": []},
        {"path": "c.md", "title": "Bar", "content": "z", "referenced_entity_uids": []},
    ]
    g = group_pages_by_entity_name(rows)
    assert len(g["Foo"]) == 2
    assert len(g["Bar"]) == 1


def test_cosine_orthogonal() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0, abs=0.01)


def test_cosine_identical() -> None:
    v = [0.1, 0.2, 0.3]
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=0.01)


@pytest.mark.asyncio
async def test_detector_skips_high_similarity_without_llm() -> None:
    store = MagicMock()
    llm = MagicMock()
    llm.generate = AsyncMock()
    det = ContradictionDetector(
        graph=store,
        embedding_fn=AsyncMock(),
        llm=llm,
        similarity_threshold=0.85,
    )
    out = await det._maybe_flag_pair(
        page_a={"path": "a.md", "title": "T"},
        page_b={"path": "b.md", "title": "T"},
        similarity=0.9,
        repository="r",
    )
    assert out is None
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_detector_invokes_llm_when_low_similarity_and_contradiction() -> None:
    store = MagicMock()
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=json.dumps(
            {
                "is_contradiction": True,
                "description": "Conflicting return types",
                "severity": "high",
            },
        ),
    )
    det = ContradictionDetector(
        graph=store,
        embedding_fn=AsyncMock(),
        llm=llm,
        similarity_threshold=0.9,
    )
    out = await det._maybe_flag_pair(
        page_a={"path": "a.md", "title": "T"},
        page_b={"path": "b.md", "title": "T"},
        similarity=0.1,
        repository="r",
    )
    assert out is not None
    assert isinstance(out, ContradictionRecord)
    assert out.severity == "high"
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_detect_scans_entity_group() -> None:
    store = MagicMock()
    async def _emb(_title: str, content: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "one two" in content else [0.0, 1.0, 0.0]

    emb = AsyncMock(side_effect=_emb)
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=json.dumps(
            {
                "is_contradiction": True,
                "description": "Mismatch",
                "severity": "medium",
            },
        ),
    )
    det = ContradictionDetector(
        graph=store,
        embedding_fn=emb,
        llm=llm,
        similarity_threshold=0.99,
    )
    pages = [
        {"path": "a.md", "title": "E", "content": "one two three", "referenced_entity_uids": []},
        {"path": "b.md", "title": "E", "content": "x", "referenced_entity_uids": []},
    ]
    out = await det.detect(pages, repository="repo1")
    assert len(out) == 1
    assert out[0].page_uid_a == "WikiPage:repo1:a.md"
    assert out[0].page_uid_b == "WikiPage:repo1:b.md"
