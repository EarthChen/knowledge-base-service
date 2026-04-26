"""Tests for wiki.memory_tiers — MemoryNode, MemoryTier, MemoryTierManager."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore
from wiki.memory_tiers import MemoryNode, MemoryTier, MemoryTierManager


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


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


@pytest.fixture
def mgr() -> MemoryTierManager:
    return MemoryTierManager()


def test_tier0_after_24h_access2_promotes_to_t1(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(hours=25)
    n = MemoryNode(
        uid="u1",
        tier=MemoryTier.WORKING,
        content="c",
        entity_name="e",
        repository="r",
        access_count=2,
        created_at=_iso(created),
        confidence=0.0,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.tier == MemoryTier.EPISODIC


def test_tier0_after_24h_low_access_expires(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(hours=30)
    n = MemoryNode(
        uid="u1",
        tier=MemoryTier.WORKING,
        content="c",
        entity_name="e",
        repository="r",
        access_count=1,
        created_at=_iso(created),
        confidence=0.0,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.status == "expired"


def test_tier1_after_7d_confirm3_promotes_to_t2(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=8)
    n = MemoryNode(
        uid="u1",
        tier=MemoryTier.EPISODIC,
        content="c",
        entity_name="e",
        repository="r",
        confirmation_count=3,
        access_count=1,
        created_at=_iso(created),
        confidence=0.5,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.tier == MemoryTier.SEMANTIC


def test_tier1_after_7d_low_confirm_expires(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)
    n = MemoryNode(
        uid="u1",
        tier=MemoryTier.EPISODIC,
        content="c",
        entity_name="e",
        repository="r",
        confirmation_count=2,
        access_count=5,
        created_at=_iso(created),
        confidence=0.9,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.status == "expired"


def test_tier2_to_t3_requires_access_10_and_conf_08(mgr: MemoryTierManager) -> None:
    n = MemoryNode(
        uid="u1",
        tier=MemoryTier.SEMANTIC,
        content="c",
        entity_name="e",
        repository="r",
        access_count=10,
        confirmation_count=3,
        created_at="2020-01-01T00:00:00Z",
        confidence=0.8,
    )
    out = mgr.apply_promotion_rules(n, now=datetime.now(timezone.utc))
    assert out.tier == MemoryTier.PROCEDURAL


@pytest.mark.asyncio
async def test_update_wiki_qa_memory_emits_cypher() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    s = WikiStore(base)
    await s.update_wiki_qa_memory(
        uid="u1", tier=2, memory_status="active", promoted_at="2026-01-01T00:00:00Z",
    )
    cypher = base.execute_query.call_args[0][0].lower()
    assert "match" in cypher
    assert "wikiqa" in cypher
    assert "tier" in cypher
    assert "memory_status" in cypher
