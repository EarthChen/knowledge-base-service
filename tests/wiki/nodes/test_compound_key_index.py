"""Test compound key prevents multi-repo name collisions."""

from unittest.mock import MagicMock, patch

from wiki.entity_role_classifier import WikiEntityRole
from wiki.nodes.graph_domain_decompose import _filter_biz_modules


def test_same_name_different_repos_no_collision():
    entity_roles = {
        "uid1": WikiEntityRole.HAS_BUSINESS_LOGIC,
        "uid2": WikiEntityRole.HAS_BUSINESS_LOGIC,
    }
    modules = {
        "repo-a": [{"uid": "uid1", "properties": {"name": "UserService", "path": "a/user.py", "business_summary": "Users in A"}}],
        "repo-b": [{"uid": "uid2", "properties": {"name": "UserService", "path": "b/user.py", "business_summary": "Users in B"}}],
    }
    with patch("wiki.nodes.graph_domain_decompose.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.classify_include_supporting = True
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        biz, _, paths, docs = _filter_biz_modules(entity_roles, modules)

    assert "repo-a|UserService" in paths
    assert "repo-b|UserService" in paths
    assert paths["repo-a|UserService"] == "a/user.py"
    assert paths["repo-b|UserService"] == "b/user.py"
    assert docs["repo-a|UserService"] == "Users in A"
    assert docs["repo-b|UserService"] == "Users in B"
    assert ("repo-a", "UserService") in biz
    assert ("repo-b", "UserService") in biz
