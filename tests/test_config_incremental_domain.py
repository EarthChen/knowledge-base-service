import pytest
from config import AppWikiFlags


@pytest.mark.skip(reason="AppWikiFlags.domain_classification_cache_enabled not implemented yet")
def test_domain_classification_cache_enabled_default():
    cfg = AppWikiFlags()
    assert cfg.domain_classification_cache_enabled is True


@pytest.mark.skip(reason="AppWikiFlags.domain_classification_cache_enabled not implemented yet")
def test_domain_classification_cache_enabled_override():
    cfg = AppWikiFlags(domain_classification_cache_enabled=False)
    assert cfg.domain_classification_cache_enabled is False
