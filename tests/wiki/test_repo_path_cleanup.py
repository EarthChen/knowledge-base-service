from __future__ import annotations

from wiki.cross_repo_domain_planner import clean_repo_path


def test_strips_gitlab_group_prefix():
    assert clean_repo_path("ultron/ultron-basic-user") == "ultron-basic-user"


def test_strips_deep_prefix():
    assert clean_repo_path("org/team/my-service") == "my-service"


def test_no_prefix_unchanged():
    assert clean_repo_path("my-service") == "my-service"


def test_empty_string():
    assert clean_repo_path("") == ""
