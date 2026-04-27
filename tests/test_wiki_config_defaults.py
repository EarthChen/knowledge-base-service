from config import WikiConfig


def test_wiki_lint_and_auto_heal_defaults_enabled() -> None:
    c = WikiConfig()
    assert c.lint_scheduler_enabled is True
    assert c.auto_heal_enabled is True
