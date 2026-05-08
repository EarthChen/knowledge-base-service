from wiki.agent_config import AgentConfig


class TestAgentConfig:
    def test_defaults(self):
        config = AgentConfig()
        assert config.enabled is False
        assert config.simple_threshold == 3

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WIKI__AGENT_DRIVEN_GENERATION", "true")
        monkeypatch.setenv("WIKI__AGENT_SIMPLE_THRESHOLD", "5")
        config = AgentConfig.from_env()
        assert config.enabled is True
        assert config.simple_threshold == 5

    def test_should_use_agent_simple(self):
        config = AgentConfig(enabled=True, simple_threshold=3)
        assert config.should_use_agent(module_count=2) is False

    def test_should_use_agent_complex(self):
        config = AgentConfig(enabled=True, simple_threshold=3)
        assert config.should_use_agent(module_count=5) is True

    def test_should_use_agent_disabled(self):
        config = AgentConfig(enabled=False, simple_threshold=3)
        assert config.should_use_agent(module_count=10) is False
