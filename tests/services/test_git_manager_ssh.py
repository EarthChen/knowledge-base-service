"""Tests for GitManager SSH environment configuration."""

from core.config import GitConfig
from services.git_manager import GitManager


def test_build_env_ssh_uses_accept_new_host_key_checking():
    cfg = GitConfig(ssh_key_path="/path/to/deploy_key")
    mgr = GitManager(cfg)
    env = mgr._build_env()

    ssh_cmd = env["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=accept-new" in ssh_cmd
    assert "StrictHostKeyChecking=no" not in ssh_cmd
    assert "UserKnownHostsFile" not in ssh_cmd
    assert "/path/to/deploy_key" in ssh_cmd


def test_build_env_omits_ssh_command_without_key():
    cfg = GitConfig(ssh_key_path="")
    mgr = GitManager(cfg)
    env = mgr._build_env()

    assert "GIT_SSH_COMMAND" not in env
