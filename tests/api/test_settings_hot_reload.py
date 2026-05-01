from __future__ import annotations

from api.routes.settings_routes import HOT_RELOAD_KEYS


def test_llm_keys_hot_reload() -> None:
    assert "llm.providers" in HOT_RELOAD_KEYS
    assert "llm.strategy.classification" in HOT_RELOAD_KEYS
    assert "llm.strategy.generation" in HOT_RELOAD_KEYS
    assert "llm.strategy.rag_plan" in HOT_RELOAD_KEYS
    assert "llm.strategy.rag_generate" in HOT_RELOAD_KEYS


def test_wiki_auto_update_still_hot() -> None:
    assert "wiki.auto_update_on_index" in HOT_RELOAD_KEYS
