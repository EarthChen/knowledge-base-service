"""Phase 5: Per-run config overrides.

Tests verify that POST /wiki/business/generate accepts optional config_overrides
and that overrides are merged into pipeline state config.
"""

from __future__ import annotations

from api.models.wiki_models import BusinessWikiGenerateBody

# ---------------------------------------------------------------------------
# Phase 5a: BusinessWikiGenerateBody accepts config_overrides
# ---------------------------------------------------------------------------


def test_generate_body_accepts_config_overrides() -> None:
    """BusinessWikiGenerateBody has config_overrides field with default empty dict."""
    body = BusinessWikiGenerateBody(
        business_id="test-biz",
        language="en",
    )
    assert body.config_overrides == {}


def test_generate_body_config_overrides_from_dict() -> None:
    """BusinessWikiGenerateBody parses config_overrides from input dict."""
    body = BusinessWikiGenerateBody(
        business_id="test-biz",
        config_overrides={
            "compose_concurrency": 32,
            "domain_agent_concurrency": 12,
            "heal_concurrency": 5,
        },
    )
    assert body.config_overrides["compose_concurrency"] == 32
    assert body.config_overrides["domain_agent_concurrency"] == 12
    assert body.config_overrides["heal_concurrency"] == 5


def test_generate_body_config_overrides_unrelated_keys() -> None:
    """config_overrides can contain arbitrary pipeline config keys."""
    body = BusinessWikiGenerateBody(
        business_id="test-biz",
        config_overrides={
            "custom_flag": True,
            "max_pages": 500,
            "language_override": "zh",
        },
    )
    assert body.config_overrides["custom_flag"] is True
    assert body.config_overrides["max_pages"] == 500


# ---------------------------------------------------------------------------
# Phase 5b: PipelineConcurrency.refresh() with overrides
# ---------------------------------------------------------------------------


def test_pipeline_concurrency_refresh_applies_overrides() -> None:
    """PipelineConcurrency.refresh(overrides=...) sets runtime overrides."""
    from wiki.pipeline_concurrency import PipelineConcurrency

    PipelineConcurrency.reset()
    PipelineConcurrency.refresh(overrides={"compose_concurrency": 99})
    assert PipelineConcurrency.limit("compose_concurrency") == 99
    PipelineConcurrency.reset()


def test_pipeline_concurrency_refresh_overrides_take_priority() -> None:
    """Runtime overrides have higher priority than env vars and config."""
    import os

    from wiki.pipeline_concurrency import PipelineConcurrency

    PipelineConcurrency.reset()
    os.environ["WIKI_COMPOSE_CONCURRENCY"] = "42"
    try:
        PipelineConcurrency.refresh(overrides={"compose_concurrency": 99})
        assert PipelineConcurrency.limit("compose_concurrency") == 99
    finally:
        del os.environ["WIKI_COMPOSE_CONCURRENCY"]
        PipelineConcurrency.reset()


def test_pipeline_concurrency_refresh_clears_semaphore_cache() -> None:
    """refresh() clears cached semaphores so new limits apply immediately."""
    from wiki.pipeline_concurrency import PipelineConcurrency

    PipelineConcurrency.reset()
    _ = PipelineConcurrency.semaphore("compose_concurrency")

    PipelineConcurrency.refresh(overrides={"compose_concurrency": 50})
    assert PipelineConcurrency.limit("compose_concurrency") == 50
    # A new semaphore should have the new limit
    sem = PipelineConcurrency.semaphore("compose_concurrency")
    assert sem._value == 50  # type: ignore[attr-defined]
    PipelineConcurrency.reset()


# ---------------------------------------------------------------------------
# Phase 5c: PipelineConcurrency not called with non-concurrency overrides
# ---------------------------------------------------------------------------


def test_pipeline_concurrency_refresh_none_clears_overrides() -> None:
    """refresh(overrides=None) clears any previous overrides."""
    from wiki.pipeline_concurrency import PipelineConcurrency

    PipelineConcurrency.reset()
    PipelineConcurrency.refresh(overrides={"compose_concurrency": 99})
    assert PipelineConcurrency.limit("compose_concurrency") == 99

    PipelineConcurrency.refresh(overrides=None)
    # Should fall back to config default (not 99)
    assert PipelineConcurrency.limit("compose_concurrency") != 99
    PipelineConcurrency.reset()
