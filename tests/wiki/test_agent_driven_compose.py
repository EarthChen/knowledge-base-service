"""Verify AgentConfig is checked in _compose_single_leaf_domain."""


def test_compose_checks_agent_config():
    """_compose_single_leaf_domain must import and check AgentConfig."""
    with open("wiki/nodes/compose.py") as f:
        source = f.read()
    assert "AgentConfig" in source, "compose.py must reference AgentConfig"
    assert "should_use_agent" in source, "compose.py must call should_use_agent"


def test_compose_has_agent_generate_path():
    """_compose_single_leaf_domain must have a path that calls agent.generate."""
    with open("wiki/nodes/compose.py") as f:
        source = f.read()
    assert "agent.generate(" in source or ".generate(" in source, (
        "compose.py must have WikiPageAgent.generate path"
    )
    assert "AgentConfig.from_env" in source or "AgentConfig(" in source, (
        "compose.py must instantiate AgentConfig"
    )
