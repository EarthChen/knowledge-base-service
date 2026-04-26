# tests/wiki/test_coverage_analyzer.py
"""Unit tests for WikiCoverageAnalyzer."""

import pytest
from unittest.mock import AsyncMock

from wiki.coverage_analyzer import WikiCoverageAnalyzer, CoverageReport


class TestCoverageReport:
    def test_dataclass_fields(self):
        report = CoverageReport(
            total_entities=100, covered_entities=80,
            core_coverage=0.95, standard_coverage=0.75,
            stale_pages=[], knowledge_gaps=[],
        )
        assert report.total_entities == 100
        assert report.covered_entities == 80
        assert report.core_coverage == 0.95

    def test_coverage_percentage(self):
        report = CoverageReport(
            total_entities=50, covered_entities=40,
            core_coverage=0.9, standard_coverage=0.7,
            stale_pages=[], knowledge_gaps=[],
        )
        assert report.coverage_percentage == 80.0

    def test_zero_entities_coverage(self):
        report = CoverageReport(
            total_entities=0, covered_entities=0,
            core_coverage=0.0, standard_coverage=0.0,
            stale_pages=[], knowledge_gaps=[],
        )
        assert report.coverage_percentage == 0.0


class TestWikiCoverageAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_with_full_coverage(self):
        """No skeleton pages — everything is core or standard."""
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 50, "covered_entities": 50,
            "core_total": 10, "standard_total": 40, "skeleton_total": 0,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("test-biz")
        assert report.total_entities == 50
        assert report.covered_entities == 50
        assert report.core_coverage == 0.2   # 10/50
        assert report.standard_coverage == 1.0  # 50/50
        assert len(report.knowledge_gaps) == 0

    @pytest.mark.asyncio
    async def test_analyze_with_partial_coverage(self):
        """Mix of core, standard, and skeleton pages."""
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 100, "covered_entities": 60,
            "core_total": 20, "standard_total": 40, "skeleton_total": 40,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[
            {"entity_name": "CacheService", "in_degree": 12, "wiki_tier": "skeleton"},
            {"entity_name": "PaymentGateway", "in_degree": 8, "wiki_tier": None},
        ])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("test-biz")
        assert report.total_entities == 100
        assert report.covered_entities == 60
        assert report.core_coverage == 0.2   # 20/100
        assert report.standard_coverage == 0.6  # 60/100
        assert len(report.knowledge_gaps) == 2

    @pytest.mark.asyncio
    async def test_analyze_empty_db(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 0, "covered_entities": 0,
            "core_total": 0, "standard_total": 0, "skeleton_total": 0,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("empty-biz")
        assert report.total_entities == 0
        assert report.coverage_percentage == 0.0

    @pytest.mark.asyncio
    async def test_analyze_core_and_standard_differ(self):
        """core_coverage and standard_coverage must be different when skeleton exists."""
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 10, "covered_entities": 7,
            "core_total": 3, "standard_total": 4, "skeleton_total": 3,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("biz-1")
        assert report.core_coverage == 0.3   # 3/10
        assert report.standard_coverage == 0.7  # 7/10
        assert report.core_coverage < report.standard_coverage

    @pytest.mark.asyncio
    async def test_report_to_dict(self):
        report = CoverageReport(
            total_entities=50, covered_entities=40,
            core_coverage=0.9, standard_coverage=0.7,
            stale_pages=[], knowledge_gaps=[{"entity": "X", "in_degree": 5}],
        )
        d = report.to_dict()
        assert d["total_entities"] == 50
        assert d["coverage_percentage"] == 80.0
        assert len(d["knowledge_gaps"]) == 1
