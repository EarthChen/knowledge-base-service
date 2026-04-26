from config import Settings


def test_wiki_enrichment_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.enrichment_enabled is True
    assert s.wiki.enrichment_round1_enabled is True
    assert s.wiki.enrichment_round2_enabled is True


def test_wiki_business_domain_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.business_domain_enabled is False
    assert s.wiki.business_domain_infrastructure_label == "__infrastructure__"
