"""Tests for contradiction detection in WikiLintService."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.wiki.test_lint import ScriptedStore
from wiki.contradiction_detector import ContradictionRecord
from wiki.lint import WikiLintService


@pytest.mark.asyncio
async def test_lint_calls_contradiction_detector_when_enabled() -> None:
    det = MagicMock()
    rec = ContradictionRecord("WikiPage:r:a.md", "WikiPage:r:b.md", "desc", "low")
    det.detect = AsyncMock(return_value=[rec])

    def script(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "RETURN count(wp) AS cnt" in cypher:
            return [{"cnt": 2}]
        if "stale_uid" in cypher:
            return []
        if "OPTIONAL MATCH (src:WikiPage)-[:WIKI_REFERENCES {relation_type: 'wikilink'}]->(wp)" in cypher:
            return [
                {"path": "a.md", "in_degree": 1},
                {"path": "b.md", "in_degree": 1},
            ]
        if "wp.path AS path" in cypher and "content AS content" in cypher:
            return [
                {
                    "path": "a.md",
                    "title": "E",
                    "content": "x",
                    "generated_at": "2099-01-01T00:00:00+00:00",
                    "referenced_entity_uids": [],
                },
                {
                    "path": "b.md",
                    "title": "E",
                    "content": "y",
                    "generated_at": "2099-01-01T00:00:00+00:00",
                    "referenced_entity_uids": [],
                },
            ]
        if "semantic_roles" in cypher:
            return []
        if "WikiContradiction" in cypher:
            return []
        return []

    base = ScriptedStore(script)
    reg = MagicMock()
    reg.list_all = MagicMock(return_value=[])
    wc = SimpleNamespace(contradiction_detection_enabled=True)
    svc = WikiLintService(
        base,
        repo_registry=reg,
        wiki_config=wc,
        contradiction_detector=det,
    )
    report = await svc.lint("r", scope="all")
    det.detect.assert_awaited_once()
    assert any(i.category == "contradiction" for i in report.issues)
