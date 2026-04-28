from config import Settings, WikiConfig


def test_wiki_lint_and_auto_heal_defaults_enabled() -> None:
    c = WikiConfig()
    assert c.lint_scheduler_enabled is True
    assert c.auto_heal_enabled is True


def test_wiki_supersession_default_enabled() -> None:
    s = Settings()
    assert s.wiki.supersession_tracking_enabled is True


def test_wiki_compose_concurrency_default() -> None:
    assert WikiConfig().compose_concurrency == 3
