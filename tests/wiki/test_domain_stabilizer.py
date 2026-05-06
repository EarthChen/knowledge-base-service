"""Tests for wiki.domain_stabilizer.DomainStabilizer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.domain_stabilizer import DomainStabilizer


def test_normalize_strips_common_suffixes():
    ds = DomainStabilizer()
    assert ds.normalize_domain_name("Meeting Management") == ds.normalize_domain_name("Meeting")
    assert ds.normalize_domain_name("用户管理") == ds.normalize_domain_name("用户")


def test_exact_match_similarity():
    ds = DomainStabilizer()
    assert ds.compute_similarity("Meeting", "Meeting") == 1.0


def test_containment_similarity():
    ds = DomainStabilizer()
    sim = ds.compute_similarity("Meeting", "Meeting Management")
    assert sim >= 0.85


def test_different_names_low_similarity():
    ds = DomainStabilizer()
    sim = ds.compute_similarity("Meeting", "Payment")
    assert sim < 0.5


def test_stabilize_sync_maps_to_existing():
    ds = DomainStabilizer(similarity_threshold=0.8)
    result = ds.stabilize_sync(
        proposed_domains=["Meeting Management", "Live Broadcasting"],
        existing_domains=["Meeting", "Live Streaming"],
    )
    assert result["Meeting Management"] == "Meeting"


def test_stabilize_sync_keeps_novel_names():
    ds = DomainStabilizer(similarity_threshold=0.8)
    result = ds.stabilize_sync(
        proposed_domains=["Brand New Feature"],
        existing_domains=["Meeting", "Live"],
    )
    assert result["Brand New Feature"] == "Brand New Feature"


@pytest.mark.asyncio
async def test_stabilize_with_graph_store():
    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[{"domain": "Meeting"}, {"domain": "Live Streaming"}],
        ),
    )

    ds = DomainStabilizer(graph_store=mock_graph, similarity_threshold=0.8)
    result = await ds.stabilize(["Meeting Management"])
    assert result["Meeting Management"] == "Meeting"


def test_chinese_domain_stabilization():
    ds = DomainStabilizer(similarity_threshold=0.7)
    result = ds.stabilize_sync(
        proposed_domains=["会议管理模块"],
        existing_domains=["会议"],
    )
    assert result["会议管理模块"] == "会议"
