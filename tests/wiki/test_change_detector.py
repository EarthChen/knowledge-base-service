from wiki.change_detector import AffectedPageSet, ChangeDetector

SAMPLE_DIFF = """M\tauth.py
A\tutils/new_helper.py
D\told_module.py
"""


def test_parse_git_diff_name_status():
    files = ChangeDetector._parse_diff_output(SAMPLE_DIFF)
    assert files == ["auth.py", "utils/new_helper.py", "old_module.py"]


def test_parse_empty_diff():
    assert ChangeDetector._parse_diff_output("") == []
    assert ChangeDetector._parse_diff_output("\n\n") == []


def test_affected_page_set_defaults():
    aps = AffectedPageSet()
    assert aps.page_uids == []
    assert aps.trigger == "manual"
