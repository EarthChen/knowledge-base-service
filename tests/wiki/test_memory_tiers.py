"""Tests for wiki.memory_tiers — MemoryNode, MemoryTier."""

from __future__ import annotations

from wiki.memory_tiers import MemoryNode, MemoryTier


def test_memory_tier_value_range() -> None:
    assert MemoryTier.WORKING.value == 0
    assert MemoryTier.EPISODIC.value == 1
    assert MemoryTier.SEMANTIC.value == 2
    assert MemoryTier.PROCEDURAL.value == 3


def test_memory_node_defaults() -> None:
    n = MemoryNode(
        uid="WikiQA:default:x",
        tier=MemoryTier.WORKING,
        content="Q\nA",
        entity_name="",
        repository="r1",
    )
    assert n.access_count == 0
    assert n.confirmation_count == 0
    assert n.stability_factor == 7.0


def test_from_wiki_qa_row_maps_content_and_default_tier() -> None:
    n = MemoryNode.from_wiki_qa_row(
        {
            "uid": "WikiQA:x:y",
            "question": "Q?",
            "answer": "A.",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    assert n.uid == "WikiQA:x:y"
    assert n.content == "Q?\nA."
    assert n.tier == MemoryTier.EPISODIC
    assert n.status == "active"


def test_from_wiki_qa_row_respects_tier() -> None:
    n = MemoryNode.from_wiki_qa_row(
        {
            "uid": "u1",
            "question": "q",
            "answer": "a",
            "tier": 2,
        },
    )
    assert n.tier == MemoryTier.SEMANTIC
