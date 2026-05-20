"""Verify TokenBudgetResolver is not shared via global state."""

import pytest
from wiki.token_budget import TokenBudgetResolver


def test_wiki_context_budget_with_explicit_resolver():
    """Budget function works with explicit resolver."""
    from wiki.ask import wiki_context_token_budget

    resolver = TokenBudgetResolver(base=2000, ceiling=128_000)
    budget = wiki_context_token_budget("what is X?", "concept", resolver=resolver)
    assert budget > 0


def test_wiki_context_budget_without_resolver_uses_fallback():
    """Without resolver, falls back to static budget table."""
    from wiki.ask import wiki_context_token_budget

    budget = wiki_context_token_budget("what is X?", "concept")
    assert budget > 0


def test_service_init_does_not_set_global_resolver():
    """WikiService.__init__ must NOT call set_default_resolver."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from core.config import AppWikiFlags, EmbeddingConfig
    from wiki.ask import _default_resolver as before
    from wiki.service import WikiService

    with patch("wiki.service.get_settings") as mock_settings:
        mock_settings.return_value.llm = MagicMock(max_context_tokens=128_000)
        WikiService(
            graph=MagicMock(),
            llm=None,
            repository_exists=AsyncMock(return_value=True),
            wiki_config=AppWikiFlags(),
            embedding_config=EmbeddingConfig(),
        )

    from wiki.ask import _default_resolver as after

    # Global should not have been mutated by constructor
    assert after is before
