"""Tests for domain budget configuration flags."""
from __future__ import annotations

import pytest


class TestDomainBudgetConfig:
    def test_domain_budget_max_default(self):
        """domain_budget_max should default to 50."""
        from core.config import AppWikiFlags

        cfg = AppWikiFlags()
        assert cfg.domain_budget_max == 50

    def test_domain_budget_max_custom(self):
        """domain_budget_max should accept custom values."""
        from core.config import AppWikiFlags

        cfg = AppWikiFlags(domain_budget_max=30)
        assert cfg.domain_budget_max == 30

    def test_domain_budget_max_min_bound(self):
        """domain_budget_max must be >= 5."""
        from core.config import AppWikiFlags
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AppWikiFlags(domain_budget_max=2)


class TestContentQualityConfig:
    def test_overview_min_content_chars_default(self):
        from core.config import AppWikiFlags

        cfg = AppWikiFlags()
        assert cfg.overview_min_content_chars == 2000

    def test_overview_min_content_chars_custom(self):
        from core.config import AppWikiFlags

        cfg = AppWikiFlags(overview_min_content_chars=3000)
        assert cfg.overview_min_content_chars == 3000

    def test_language_guardrail_cn_ratio_default(self):
        from core.config import AppWikiFlags

        cfg = AppWikiFlags()
        assert cfg.language_guardrail_cn_ratio == 0.4

    def test_auto_cleanup_checkpoint_default_false(self):
        from core.config import AppWikiFlags

        cfg = AppWikiFlags()
        assert cfg.auto_cleanup_checkpoint is False

    def test_prefer_graph_for_incremental_default_true(self):
        from core.config import AppWikiFlags

        cfg = AppWikiFlags()
        assert cfg.prefer_graph_for_incremental is True
