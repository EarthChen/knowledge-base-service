# tests/wiki/test_coverage_analyzer.py
"""Unit tests for WikiCoverageAnalyzer."""

import pytest
from unittest.mock import AsyncMock

from wiki.coverage_analyzer import WikiCoverageAnalyzer, CoverageReport


class TestCoverageReport:
    def test_dataclass_fields(self):
        report = CoverageReport(
            total_modules=100,
            covered_modules=80,
            stale_pages=[],
            knowledge_gaps=[],
        )
        assert report.total_modules == 100
        assert report.covered_modules == 80

    def test_coverage_percentage(self):
        report = CoverageReport(
            total_modules=50,
            covered_modules=40,
            stale_pages=[],
            knowledge_gaps=[],
        )
        assert report.coverage_percentage == 80.0

    def test_zero_modules_coverage(self):
        report = CoverageReport(
            total_modules=0,
            covered_modules=0,
            stale_pages=[],
            knowledge_gaps=[],
        )
        assert report.coverage_percentage == 0.0


class TestWikiCoverageAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_full_module_coverage(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_modules": 50,
            "covered_modules": 50,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("test-biz")
        assert report.total_modules == 50
        assert report.covered_modules == 50
        assert report.coverage_percentage == 100.0
        assert len(report.knowledge_gaps) == 0

    @pytest.mark.asyncio
    async def test_analyze_partial_module_coverage(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_modules": 100,
            "covered_modules": 60,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[
            {"entity_name": "CacheService", "in_degree": 12, "wiki_tier": "skeleton"},
            {"entity_name": "PaymentGateway", "in_degree": 8, "wiki_tier": None},
        ])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("test-biz")
        assert report.total_modules == 100
        assert report.covered_modules == 60
        assert report.coverage_percentage == 60.0
        assert len(report.knowledge_gaps) == 2

    @pytest.mark.asyncio
    async def test_analyze_empty_db(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_modules": 0,
            "covered_modules": 0,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("empty-biz")
        assert report.total_modules == 0
        assert report.coverage_percentage == 0.0

    @pytest.mark.asyncio
    async def test_report_to_dict(self):
        report = CoverageReport(
            total_modules=50,
            covered_modules=40,
            stale_pages=[],
            knowledge_gaps=[{"entity": "X", "in_degree": 5}],
        )
        d = report.to_dict()
        assert d["total_modules"] == 50
        assert d["covered_modules"] == 40
        assert d["coverage_percentage"] == 80.0
        assert len(d["knowledge_gaps"]) == 1
        assert "core_coverage" not in d


class TestStaleDetection:
    @pytest.mark.asyncio
    async def test_detect_stale_pages(self):
        mock_store = AsyncMock()
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[
            {"page_path": "/用户管理/UserService", "page_title": "UserService",
             "entity_commit": "abc123", "page_generated_at": "2026-04-20"},
        ])
        analyzer = WikiCoverageAnalyzer(mock_store)
        stale = await analyzer.detect_stale_pages("test-biz")
        assert len(stale) == 1
        assert stale[0]["page_path"] == "/用户管理/UserService"

    @pytest.mark.asyncio
    async def test_no_stale_pages(self):
        mock_store = AsyncMock()
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        stale = await analyzer.detect_stale_pages("test-biz")
        assert stale == []

    @pytest.mark.asyncio
    async def test_analyze_includes_stale_pages(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_modules": 10,
            "covered_modules": 8,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[
            {"page_path": "/Domain/Old", "page_title": "Old",
             "entity_commit": "new123", "page_generated_at": "2026-04-01"},
        ])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("biz")
        assert len(report.stale_pages) == 1
        assert report.stale_pages[0]["page_path"] == "/Domain/Old"

    @pytest.mark.asyncio
    async def test_to_dict_includes_stale_count(self):
        report = CoverageReport(
            total_modules=10,
            covered_modules=8,
            stale_pages=[
                {"page_path": "/A", "page_title": "A",
                 "entity_commit": "x", "page_generated_at": "2026-01-01"},
                {"page_path": "/B", "page_title": "B",
                 "entity_commit": "y", "page_generated_at": "2026-01-01"},
            ],
            knowledge_gaps=[],
        )
        d = report.to_dict()
        assert d["stale_page_count"] == 2
        assert len(d["stale_pages"]) == 2
