"""Tests for default indexing LLM enrichment flags."""

from __future__ import annotations


def test_default_synthesis_max_tokens(monkeypatch) -> None:
    monkeypatch.delenv("LLM__SYNTHESIS_MAX_TOKENS", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.synthesis_max_tokens == 2000


def test_default_business_summary_enrichment_enabled(monkeypatch) -> None:
    monkeypatch.delenv("LLM__GATEWAY__ENRICHMENT_ENABLED", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.gateway.enrichment_enabled is True


def test_default_concept_extraction_disabled(monkeypatch) -> None:
    monkeypatch.delenv("LLM__CONCEPT_EXTRACTION_ENABLED", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.concept_extraction_enabled is False


def test_default_business_flow_disabled(monkeypatch) -> None:
    monkeypatch.delenv("LLM__BUSINESS_FLOW_ENABLED", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.business_flow_enabled is False


def test_concept_extraction_and_business_flow_can_be_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM__CONCEPT_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("LLM__BUSINESS_FLOW_ENABLED", "true")
    from core.config import Settings

    s = Settings()
    assert s.llm.concept_extraction_enabled is True
    assert s.llm.business_flow_enabled is True


def test_enrichment_strategy_default_is_disabled(monkeypatch) -> None:
    monkeypatch.delenv("LLM__ENRICHMENT_STRATEGY", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.enrichment_strategy == "disabled"


def test_enrichment_strategy_core_only_valid(monkeypatch) -> None:
    monkeypatch.setenv("LLM__ENRICHMENT_STRATEGY", "core_only")
    from core.config import Settings

    s = Settings()
    assert s.llm.enrichment_strategy == "core_only"
