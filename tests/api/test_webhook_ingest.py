import pytest


def test_parse_github_push_payload():
    """Extract changed files from a GitHub push webhook payload."""
    payload = {
        "commits": [
            {"added": ["new.py"], "modified": ["auth.py"], "removed": ["old.py"]},
            {"added": [], "modified": ["utils.py"], "removed": []},
        ],
    }
    from api.routes.webhook_routes import _extract_files_from_push_payload

    files = _extract_files_from_push_payload(payload)
    assert set(files) == {"new.py", "auth.py", "old.py", "utils.py"}


def test_parse_empty_payload():
    from api.routes.webhook_routes import _extract_files_from_push_payload

    assert _extract_files_from_push_payload({}) == []
    assert _extract_files_from_push_payload({"commits": []}) == []
