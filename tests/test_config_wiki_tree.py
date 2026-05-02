from core.config import Settings


def test_wiki_tree_config_defaults():
    s = Settings(falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.tree_enabled is True
    assert s.wiki.dual_view_enabled is True
    assert s.wiki.cross_reference_enabled is True
    assert s.wiki.cross_reference_min_confidence == 0.5


def test_wiki_export_config_defaults():
    s = Settings(falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.git_publish_enabled is False
    assert s.wiki.git_publish_mode == "incremental"
    assert s.wiki.export_default_view == "business_domain"
    assert s.wiki.export_min_tier == "standard"
    assert s.wiki.export_dir_naming == "original"
