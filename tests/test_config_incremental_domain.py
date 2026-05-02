import pytest
from core.config import AppWikiFlags


def test_domain_classification_cache_enabled_default():
    cfg = AppWikiFlags()
    assert cfg.domain_classification_cache_enabled is True


def test_domain_classification_cache_enabled_override():
    cfg = AppWikiFlags(domain_classification_cache_enabled=False)
    assert cfg.domain_classification_cache_enabled is False
