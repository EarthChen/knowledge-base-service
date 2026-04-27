from config import Settings


def test_feedback_regen_defaults() -> None:
    s = Settings()
    assert s.wiki.feedback_regen_enabled is True
    assert s.wiki.feedback_regen_threshold == 3
    assert s.wiki.feedback_regen_critical_immediate is True
    assert s.wiki.feedback_regen_token_multiplier == 1.5
    assert s.wiki.feedback_regen_batch_token_multiplier == 1.2
    assert s.wiki.feedback_regen_cooldown_hours == 24
