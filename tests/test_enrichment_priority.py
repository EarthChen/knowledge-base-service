"""Tests for EnrichmentPriorityClassifier (index-time core entity selection)."""

from __future__ import annotations

import pytest

from indexer.enrichment import EnrichmentPriorityClassifier


@pytest.fixture
def classifier() -> EnrichmentPriorityClassifier:
    return EnrichmentPriorityClassifier()


class TestEnrichmentPriorityClassifier:
    def test_core_entity_by_class_suffix(self, classifier: EnrichmentPriorityClassifier) -> None:
        for suffix in ("FooController", "OrderService", "EventHandler", "TaskManager"):
            assert classifier.is_core_entity(
                {
                    "name": suffix,
                    "code_snippet": "x",
                    "entity_kind": "class",
                }
            )

    def test_core_entity_by_semantic_roles(self, classifier: EnrichmentPriorityClassifier) -> None:
        assert classifier.is_core_entity(
            {
                "name": "handle",
                "code_snippet": "def handle():\n    pass\n",
                "entity_kind": "function",
                "semantic_roles": ["http_endpoint"],
            }
        )

    def test_core_entity_by_code_complexity(self, classifier: EnrichmentPriorityClassifier) -> None:
        code = "\n".join([f"    line_{i}()" for i in range(31)])
        assert len(code.splitlines()) > 30
        assert classifier.is_core_entity(
            {
                "name": "complex_logic",
                "code_snippet": code,
                "entity_kind": "function",
            }
        )

    def test_non_core_simple_function(self, classifier: EnrichmentPriorityClassifier) -> None:
        assert not classifier.is_core_entity(
            {
                "name": "normalize_ws",
                "code_snippet": "def normalize_ws(s):\n    return s.strip()\n",
                "entity_kind": "function",
            }
        )

    def test_non_core_regular_class(self, classifier: EnrichmentPriorityClassifier) -> None:
        assert not classifier.is_core_entity(
            {
                "name": "Point",
                "code_snippet": "class Point:\n    x: int\n    y: int\n",
                "entity_kind": "class",
            }
        )
