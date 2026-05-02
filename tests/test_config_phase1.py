from core.config import Settings


def test_wiki_code_budget_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.code_budget_enabled is True
    assert s.wiki.core_code_budget == 20000
    assert s.wiki.standard_code_budget == 8000
    assert s.wiki.skeleton_code_budget == 1000


def test_wiki_importance_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.importance_core_percentile == 80
    assert s.wiki.importance_standard_percentile == 30
