"""Tests for PageRank-weighted mechanical topic assignment (G5)."""

from __future__ import annotations

from unittest.mock import MagicMock

from wiki.domain_doc_agent import (
    DomainDocAgent,
    _extract_chunk_title,
    compute_module_pagerank,
)


def test_compute_module_pagerank_simple_chain() -> None:
    """Linear chain A→B→C: middle and sink rank above the source."""
    module_names = ["A", "B", "C"]
    call_edges = [
        {"source": "A", "target": "B", "weight": 1},
        {"source": "B", "target": "C", "weight": 1},
    ]
    ranks = compute_module_pagerank(module_names, call_edges)
    assert set(ranks) == set(module_names)
    assert ranks["B"] > ranks["A"]
    assert ranks["C"] > ranks["A"]
    assert all(0.0 <= score <= 1.0 for score in ranks.values())


def test_compute_module_pagerank_star_topology() -> None:
    """Star with hub H: hub receives from all spokes and ranks highest."""
    module_names = ["A", "B", "C", "H"]
    call_edges = [
        {"source": "A", "target": "H", "weight": 1},
        {"source": "B", "target": "H", "weight": 1},
        {"source": "C", "target": "H", "weight": 1},
    ]
    ranks = compute_module_pagerank(module_names, call_edges)
    assert ranks["H"] > ranks["A"]
    assert ranks["H"] > ranks["B"]
    assert ranks["H"] > ranks["C"]


def test_compute_module_pagerank_no_edges() -> None:
    """With no call edges every module gets the same normalized rank."""
    module_names = ["X", "Y", "Z"]
    ranks = compute_module_pagerank(module_names, None)
    assert set(ranks) == set(module_names)
    assert ranks["X"] == ranks["Y"] == ranks["Z"]
    assert all(0.0 <= score <= 1.0 for score in ranks.values())


def test_compute_module_pagerank_filters_external() -> None:
    """Edges touching modules outside the domain are excluded."""
    module_names = ["A", "B"]
    call_edges = [
        {"source": "A", "target": "B", "weight": 1},
        {"source": "B", "target": "External", "weight": 5},
        {"source": "External", "target": "A", "weight": 5},
    ]
    ranks = compute_module_pagerank(module_names, call_edges)
    assert set(ranks) == {"A", "B"}
    assert "External" not in ranks


def test_mechanical_split_uses_rank_for_ordering() -> None:
    """Mechanical split orders modules by PageRank before chunking."""
    agent = DomainDocAgent(
        domain_name="ranked-domain",
        domain_display_name="Ranked Domain",
        llm=MagicMock(),
        graph_store=MagicMock(),
    )
    module_names = ["ModA", "ModB", "ModC", "ModD", "ModE", "ModF"]
    ranks = {
        "ModF": 1.0,
        "ModE": 0.9,
        "ModD": 0.8,
        "ModC": 0.7,
        "ModB": 0.6,
        "ModA": 0.5,
    }
    outline = agent._build_mechanical_topic_split(module_names, module_ranks=ranks)
    assert outline is not None
    assert len(outline.topics) == 2
    first_chunk = outline.topics[0].modules
    assert first_chunk == ["ModF", "ModE", "ModD"]
    assert outline.topics[0].title == "ModF"


def test_extract_chunk_title_prefers_high_rank() -> None:
    """When ranks are provided, title comes from highest-ranked module, not longest name."""
    modules = [
        {"name": "short", "display_name": "Short"},
        {"name": "tiny", "display_name": "Tiny"},
        {"name": "anchor", "display_name": "X"},
    ]
    ranks = {"short": 0.2, "tiny": 0.1, "anchor": 0.9}
    title = _extract_chunk_title(modules, "My Domain", 0, ranks=ranks)
    assert title == "X"


def test_mechanical_split_without_ranks_still_works() -> None:
    """Without ranks, mechanical split keeps alphabetical ordering (backward compatible)."""
    agent = DomainDocAgent(
        domain_name="alpha-domain",
        domain_display_name="Alpha Domain",
        llm=MagicMock(),
        graph_store=MagicMock(),
    )
    module_names = ["ModC", "ModA", "ModB", "ModD"]
    outline = agent._build_mechanical_topic_split(module_names)
    assert outline is not None
    assert len(outline.topics) == 2
    assert outline.topics[0].modules == ["ModA", "ModB", "ModC"]
    assert outline.topics[1].modules == ["ModD"]
