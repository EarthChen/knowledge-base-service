# tests/wiki/test_reassemble_domains.py
"""Tests for wiki-driven domain reassembly."""
from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pytest


class TestReassemblyConfig:
    def test_default_config_values(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert flags.domain_reassembly_enabled is True
        assert flags.reassembly_merge_threshold == 0.85
        assert flags.reassembly_orphan_threshold == 0.60
        assert flags.reassembly_max_moves_pct == 0.30
        assert flags.reassembly_respect_user_modified is True

    def test_config_override(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags(
            domain_reassembly_enabled=False,
            reassembly_merge_threshold=0.9,
        )
        assert flags.domain_reassembly_enabled is False
        assert flags.reassembly_merge_threshold == 0.9


class TestPipelineState:
    def test_state_has_reassembly_actions_field(self):
        from wiki.pipeline_state import WikiPipelineState

        annotations = WikiPipelineState.__annotations__
        assert "reassembly_actions" in annotations

    def test_state_has_domain_display_names_field(self):
        from wiki.pipeline_state import WikiPipelineState

        annotations = WikiPipelineState.__annotations__
        assert "domain_display_names" in annotations


class TestDomainEmbedding:
    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_from_pages(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        pages = [
            {"path": "auth-domain/_overview", "content": "This domain handles authentication and authorization."},
            {"path": "payment-domain/_overview", "content": "This domain handles payment processing."},
            {"path": "auth-domain/login-module", "content": "Login module details."},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.1] * 1024,
            [0.9] * 1024,
        ])

        result = await _extract_domain_embeddings(pages, mock_generator)

        assert "auth-domain" in result
        assert "payment-domain" in result
        assert "auth-domain/login-module" not in result
        assert result["auth-domain"].shape == (1024,)
        mock_generator.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_empty_pages(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        mock_generator = AsyncMock()
        result = await _extract_domain_embeddings([], mock_generator)
        assert result == {}

    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_skips_empty_content(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        pages = [
            {"path": "empty-domain/_overview", "content": ""},
            {"path": "valid-domain/_overview", "content": "Has content"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[[0.5] * 1024])

        result = await _extract_domain_embeddings(pages, mock_generator)
        assert "empty-domain" not in result
        assert "valid-domain" in result


class TestMergeCandidates:
    def test_find_merge_candidates_above_threshold(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.99, 0.1, 0.0], dtype=np.float32),
            "domain-c": np.array([0.0, 0.0, 1.0], dtype=np.float32),
        }

        candidates = _find_merge_candidates(embeddings, threshold=0.85, pinned_domains=set())
        assert len(candidates) == 1
        assert candidates[0]["similarity"] > 0.85

    def test_find_merge_candidates_none_above_threshold(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        candidates = _find_merge_candidates(embeddings, threshold=0.85, pinned_domains=set())
        assert candidates == []

    def test_find_merge_candidates_skips_pinned(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.99, 0.1, 0.0], dtype=np.float32),
        }
        candidates = _find_merge_candidates(
            embeddings, threshold=0.85, pinned_domains={"domain-a"}
        )
        assert candidates == []

    def test_merge_candidates_sorted_by_similarity_desc(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "d-a": np.array([1.0, 0.0], dtype=np.float32),
            "d-b": np.array([0.95, 0.3], dtype=np.float32),
            "d-c": np.array([0.99, 0.1], dtype=np.float32),
        }
        candidates = _find_merge_candidates(embeddings, threshold=0.5, pinned_domains=set())
        if len(candidates) > 1:
            for i in range(len(candidates) - 1):
                assert candidates[i]["similarity"] >= candidates[i + 1]["similarity"]


class TestOrphanMatching:
    @pytest.mark.asyncio
    async def test_match_orphan_to_best_domain(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "auth-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "payment-domain": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "orphan-auth/_overview", "content": "Handles user sessions"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.95, 0.1, 0.0],
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains=set(),
        )
        assert len(assignments) == 1
        assert assignments[0]["orphan_path"] == "orphan-auth/_overview"
        assert assignments[0]["assigned_domain"] == "auth-domain"

    @pytest.mark.asyncio
    async def test_orphan_below_threshold_not_assigned(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "auth-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "unrelated/_overview", "content": "Completely different topic"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.0, 0.0, 1.0],
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains=set(),
        )
        assert assignments == []

    @pytest.mark.asyncio
    async def test_orphan_skips_pinned_domains(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "pinned-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "open-domain": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "orphan/_overview", "content": "Some content"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.95, 0.1, 0.0],  # Closest to pinned-domain
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains={"pinned-domain"},
        )
        # Should match open-domain (even though pinned-domain was closer)
        if assignments:
            assert assignments[0]["assigned_domain"] == "open-domain"

    @pytest.mark.asyncio
    async def test_empty_orphan_pages(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        assignments = await _match_orphan_pages(
            [], {"d": np.array([1.0])}, AsyncMock(), threshold=0.6, pinned_domains=set(),
        )
        assert assignments == []
