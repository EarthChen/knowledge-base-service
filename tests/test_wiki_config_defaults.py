from core.config import AppWikiFlags, Settings


def test_business_wiki_default_mode_is_full() -> None:
    from api.models.wiki_models import BusinessWikiGenerateBody

    body = BusinessWikiGenerateBody()
    assert body.mode == "full"


def test_wiki_lint_and_auto_heal_defaults_enabled() -> None:
    c = AppWikiFlags()
    assert c.lint_scheduler_enabled is True
    assert c.auto_heal_enabled is True


def test_wiki_supersession_default_enabled() -> None:
    s = Settings()
    assert s.wiki.supersession_tracking_enabled is True


def test_wiki_compose_concurrency_default() -> None:
    assert AppWikiFlags().compose_concurrency == 6


def test_decomposition_max_tokens_deprecated_field_still_works() -> None:
    cfg = AppWikiFlags()
    assert hasattr(cfg, "decomposition_max_tokens_per_batch")
    assert hasattr(cfg, "default_llm_budget")
    assert cfg.default_llm_budget == 30_000


def test_config_has_entity_filter_flags() -> None:
    cfg = AppWikiFlags()
    assert hasattr(cfg, "entity_filter_enabled")
    assert hasattr(cfg, "max_domain_depth")
    assert hasattr(cfg, "hub_detection_percentile")
    assert cfg.entity_filter_enabled is True
    assert cfg.max_domain_depth == 4
