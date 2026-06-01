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


def test_default_concept_extraction_enabled(monkeypatch) -> None:
    monkeypatch.delenv("LLM__CONCEPT_EXTRACTION_ENABLED", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.concept_extraction_enabled is True


def test_default_business_flow_enabled(monkeypatch) -> None:
    monkeypatch.delenv("LLM__BUSINESS_FLOW_ENABLED", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.business_flow_enabled is True


def test_concept_extraction_and_business_flow_can_be_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM__CONCEPT_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("LLM__BUSINESS_FLOW_ENABLED", "true")
    from core.config import Settings

    s = Settings()
    assert s.llm.concept_extraction_enabled is True
    assert s.llm.business_flow_enabled is True


def test_enrichment_strategy_default_is_core_only(monkeypatch) -> None:
    monkeypatch.delenv("LLM__ENRICHMENT_STRATEGY", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.llm.enrichment_strategy == "core_only"


def test_enrichment_strategy_core_only_valid(monkeypatch) -> None:
    monkeypatch.setenv("LLM__ENRICHMENT_STRATEGY", "core_only")
    from core.config import Settings

    s = Settings()
    assert s.llm.enrichment_strategy == "core_only"


def test_reassembly_threshold_defaults(monkeypatch) -> None:
    monkeypatch.delenv("WIKI__REASSEMBLY_MERGE_THRESHOLD", raising=False)
    monkeypatch.delenv("WIKI__REASSEMBLY_ORPHAN_THRESHOLD", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.wiki.reassembly_merge_threshold == 0.78
    assert s.wiki.reassembly_orphan_threshold == 0.65


def test_tree_linker_shell_min_prose_ratio_default(monkeypatch) -> None:
    monkeypatch.delenv("WIKI__TREE_LINKER_SHELL_MIN_PROSE_RATIO", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.wiki.tree_linker_shell_min_prose_ratio == 0.3


def test_infra_module_patterns_default(monkeypatch) -> None:
    monkeypatch.delenv("WIKI__INFRA_MODULE_PATTERNS", raising=False)
    from core.config import Settings

    s = Settings()
    assert "core/" in s.wiki.infra_module_patterns
    assert "utils/" in s.wiki.infra_module_patterns
    assert "middleware/" in s.wiki.infra_module_patterns


def test_infra_module_fan_in_threshold_default(monkeypatch) -> None:
    monkeypatch.delenv("WIKI__INFRA_MODULE_FAN_IN_THRESHOLD", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.wiki.infra_module_fan_in_threshold == 0.5


def test_reject_mechanical_topic_names_default(monkeypatch) -> None:
    monkeypatch.delenv("WIKI__REJECT_MECHANICAL_TOPIC_NAMES", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.wiki.reject_mechanical_topic_names is True


def test_topic_stub_heading_ratio_max_default(monkeypatch) -> None:
    monkeypatch.delenv("WIKI__TOPIC_STUB_HEADING_RATIO_MAX", raising=False)
    from core.config import Settings

    s = Settings()
    assert s.wiki.topic_stub_heading_ratio_max == 0.5


def test_embedding_query_prefix_default() -> None:
    from core.config import EmbeddingConfig

    assert EmbeddingConfig().query_prefix == "Represent this sentence for searching relevant passages: "
