from config import Settings


def test_wiki_config_snapshot_defaults():
    s = Settings()
    assert s.wiki.snapshot_enabled is True
    assert s.wiki.snapshot_layer_page_threshold == 100
