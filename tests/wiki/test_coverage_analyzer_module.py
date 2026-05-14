"""Test simplified module-based CoverageReport."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_coverage_report_uses_module_counts():
    """CoverageReport should use total_modules and covered_modules."""
    from wiki.coverage_analyzer import WikiCoverageAnalyzer

    mock_store = MagicMock()
    mock_store.get_entity_coverage_stats = AsyncMock(return_value={
        "total_modules": 50,
        "covered_modules": 30,
    })
    mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
    mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])

    analyzer = WikiCoverageAnalyzer(mock_store)
    report = await analyzer.analyze("test-biz")

    assert report.total_modules == 50
    assert report.covered_modules == 30
    assert report.coverage_percentage == 60.0

    d = report.to_dict()
    assert d["total_modules"] == 50
    assert d["covered_modules"] == 30
    assert "core_coverage" not in d
    assert "standard_coverage" not in d
