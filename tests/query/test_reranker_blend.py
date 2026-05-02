"""Tests for Reranker.rerank_with_scores and position-aware blending integration."""

import pytest
from unittest.mock import MagicMock, patch

from core.config import RerankConfig
from query.reranker import Reranker


@pytest.fixture
def disabled_config():
    return RerankConfig(enabled=False, model_name="test", device="cpu")


@pytest.fixture
def enabled_config():
    return RerankConfig(enabled=True, model_name="test", device="cpu")


@pytest.fixture
def sample_candidates():
    return [
        {"name": "func_a", "file": "a.py", "line": 1, "score": 0.9, "signature": "def func_a()"},
        {"name": "func_b", "file": "b.py", "line": 10, "score": 0.7, "signature": "def func_b()"},
        {"name": "func_c", "file": "c.py", "line": 20, "score": 0.5, "signature": "def func_c()"},
    ]


class TestRerankerWithScores:
    @pytest.mark.asyncio
    async def test_disabled_returns_original_scores(self, disabled_config, sample_candidates):
        reranker = Reranker(disabled_config)
        result = await reranker.rerank_with_scores("test", sample_candidates, top_k=3)
        assert len(result) == 3
        assert all(isinstance(r, tuple) and len(r) == 2 for r in result)
        # Should use candidate's original score
        assert result[0][1] == 0.9
        assert result[1][1] == 0.7

    @pytest.mark.asyncio
    async def test_disabled_respects_top_k(self, disabled_config, sample_candidates):
        reranker = Reranker(disabled_config)
        result = await reranker.rerank_with_scores("test", sample_candidates, top_k=1)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_candidates(self, disabled_config):
        reranker = Reranker(disabled_config)
        result = await reranker.rerank_with_scores("test", [], top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_enabled_with_mock_model(self, enabled_config, sample_candidates):
        reranker = Reranker(enabled_config)
        # Mock the model
        mock_model = MagicMock()
        mock_model.predict.return_value = MagicMock(tolist=lambda: [0.3, 0.9, 0.6])
        reranker._model = mock_model

        result = await reranker.rerank_with_scores("test query", sample_candidates, top_k=3)
        assert len(result) == 3
        # Should be sorted by reranker score descending
        assert result[0][1] == pytest.approx(0.9)  # func_b
        assert result[0][0]["name"] == "func_b"

    @pytest.mark.asyncio
    async def test_enabled_model_load_fails_gracefully(self, enabled_config, sample_candidates):
        reranker = Reranker(enabled_config)
        # Don't set _model, let _ensure_model fail
        with patch.object(
            reranker,
            "_ensure_model",
            side_effect=lambda: setattr(reranker._config, "enabled", False),
        ):
            # After _ensure_model fails, _model is still None
            result = await reranker.rerank_with_scores("test", sample_candidates, top_k=2)
            assert len(result) == 2
            # Falls back to original scores
            assert result[0][1] == 0.9

    @pytest.mark.asyncio
    async def test_scores_are_floats(self, enabled_config, sample_candidates):
        reranker = Reranker(enabled_config)
        mock_model = MagicMock()
        mock_model.predict.return_value = MagicMock(tolist=lambda: [0.1, 0.5, 0.3])
        reranker._model = mock_model

        result = await reranker.rerank_with_scores("q", sample_candidates, top_k=3)
        for _, score in result:
            assert isinstance(score, float)
