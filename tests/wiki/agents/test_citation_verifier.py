from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wiki.agents.citation_verifier import CitationResult, CitationVerifier


class TestCitationExtraction:
    def test_extracts_source_refs(self):
        cv = CitationVerifier()
        content = "See `source://auth/login.py#L10-L20` and `source://auth/jwt.py#L5`."
        refs = cv.extract_citations(content)
        assert len(refs) == 2
        assert refs[0]["path"] == "auth/login.py"
        assert refs[0]["start_line"] == 10
        assert refs[0]["end_line"] == 20
        assert refs[1]["path"] == "auth/jwt.py"
        assert refs[1]["start_line"] == 5

    def test_no_citations_returns_empty(self):
        cv = CitationVerifier()
        refs = cv.extract_citations("# Simple content\nNo citations here.")
        assert refs == []

    def test_handles_malformed_refs(self):
        cv = CitationVerifier()
        content = "See `source://` and `source://path` without line ref."
        refs = cv.extract_citations(content)
        # Should handle gracefully — either skip or extract what's available
        for ref in refs:
            assert "path" in ref


class TestCitationVerification:
    @pytest.mark.asyncio
    async def test_all_valid_returns_pass(self):
        cv = CitationVerifier()
        content = "See `source://auth/login.py#L10-L20`."

        # Mock graph store that confirms path exists
        store = AsyncMock()
        store.query = AsyncMock(return_value=[[{"path": "auth/login.py", "lines": 100}]])

        result = await cv.verify(content, graph_store=store)
        assert result.valid_count >= 1
        assert result.invalid_count == 0

    @pytest.mark.asyncio
    async def test_invalid_path_detected(self):
        cv = CitationVerifier()
        content = "See `source://nonexistent/file.py#L1`."

        store = AsyncMock()
        store.query = AsyncMock(return_value=[[]])  # No match

        result = await cv.verify(content, graph_store=store)
        assert result.invalid_count >= 1
        assert len(result.invalid_refs) >= 1

    @pytest.mark.asyncio
    async def test_no_store_degrades_gracefully(self):
        cv = CitationVerifier()
        content = "See `source://auth/login.py#L10`."

        result = await cv.verify(content, graph_store=None)
        assert result.valid_count == 0
        assert result.skipped_count >= 1


class TestCitationResult:
    def test_result_fields(self):
        result = CitationResult(
            total_count=5,
            valid_count=3,
            invalid_count=1,
            skipped_count=1,
            invalid_refs=[{"path": "bad.py", "reason": "not found"}],
        )
        assert result.total_count == 5
        assert result.pass_rate == 0.6  # 3/5
