from wiki.change_detector import AffectedPageSet


def test_affected_page_set_structure():
    affected = AffectedPageSet(
        page_uids=["WikiPage:repo:auth.md", "WikiPage:repo:utils.md"],
        affected_entities=["Entity:auth", "Entity:utils"],
        trigger="git_push",
        files_changed=["auth.py", "utils.py"],
    )
    assert len(affected.page_uids) == 2
    assert affected.trigger == "git_push"


def test_empty_affected_set():
    affected = AffectedPageSet()
    assert len(affected.page_uids) == 0
