"""Tests for NL-only reranker gating via query_router.should_rerank."""

from __future__ import annotations

from core.config import RerankConfig
from query.query_router import should_rerank


class TestShouldRerank:
    def test_natural_language_query(self) -> None:
        assert should_rerank("how does authentication work") is True

    def test_code_like_fqn_query(self) -> None:
        assert should_rerank("com.example.AuthService") is False


class TestRerankConfigDefaults:
    def test_rerank_enabled_by_default(self) -> None:
        cfg = RerankConfig()
        assert cfg.enabled is True

    def test_nl_only_by_default(self) -> None:
        cfg = RerankConfig()
        assert cfg.nl_only is True
