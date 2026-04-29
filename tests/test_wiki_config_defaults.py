from config import AppWikiFlags, Settings


def test_business_wiki_default_mode_is_full() -> None:
    from api.models.wiki_models import BusinessWikiGenerateBody

    body = BusinessWikiGenerateBody()
    assert body.mode == "full"


def test_wiki_lint_and_auto_heal_defaults_enabled() -> None:
    c = AppWikiFlags()
    assert c.lint_scheduler_enabled is True
    assert c.auto_heal_enabled is True


def test_wiki_supersession_default_enabled() -> None:
    s = Settings()
    assert s.wiki.supersession_tracking_enabled is True


def test_wiki_compose_concurrency_default() -> None:
    assert AppWikiFlags().compose_concurrency == 3
