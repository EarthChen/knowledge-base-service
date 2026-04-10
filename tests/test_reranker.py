from unittest.mock import patch

from config import RerankConfig


class TestReranker:
    def test_rerank_sorts_by_score(self):
        from query.reranker import Reranker

        config = RerankConfig(enabled=True)
        reranker = Reranker(config)
        with patch.object(reranker, "_compute_scores", return_value=[0.1, 0.9, 0.5]):
            with patch.object(reranker, "_ensure_model"):
                reranker._model = True  # pretend model is loaded
                candidates = [
                    {"name": "a", "docstring": "low"},
                    {"name": "b", "docstring": "high"},
                    {"name": "c", "docstring": "medium"},
                ]
                result = reranker.rerank("test query", candidates, top_k=2)
        assert result[0]["name"] == "b"
        assert result[1]["name"] == "c"
        assert len(result) == 2

    def test_rerank_disabled_returns_original(self):
        from query.reranker import Reranker

        config = RerankConfig(enabled=False)
        reranker = Reranker(config)
        candidates = [{"name": "a"}, {"name": "b"}]
        result = reranker.rerank("query", candidates, top_k=2)
        assert result == candidates

    def test_candidate_text_prefers_business_summary(self):
        from query.reranker import Reranker

        text = Reranker._candidate_text(
            {
                "business_summary": "handles payment",
                "name": "pay",
                "docstring": "process payment",
            }
        )
        assert "handles payment" in text
        assert "pay" in text

    def test_empty_candidates(self):
        from query.reranker import Reranker

        config = RerankConfig(enabled=True)
        reranker = Reranker(config)
        result = reranker.rerank("query", [], top_k=5)
        assert result == []
