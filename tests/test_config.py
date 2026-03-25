"""Tests for knowledge base service configuration."""

from config import EmbeddingConfig, FalkorDBConfig, Settings


class TestFalkorDBConfig:
    def test_defaults(self):
        cfg = FalkorDBConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 6379
        assert cfg.password == ""
        assert cfg.graph_name == "code_knowledge"


class TestEmbeddingConfig:
    def test_defaults(self):
        cfg = EmbeddingConfig()
        assert cfg.model_name == "nomic-ai/CodeRankEmbed"
        assert cfg.dimension == 768
        assert cfg.device == "cpu"
        assert cfg.batch_size == 32


class TestSettings:
    def test_defaults(self):
        settings = Settings(
            _env_file=None,  # Prevent loading .env in tests
        )
        assert settings.host == "0.0.0.0"
        assert settings.port == 8100
        assert settings.log_level == "INFO"
        assert settings.api_token == ""

    def test_supported_languages(self):
        settings = Settings(_env_file=None)
        assert "python" in settings.supported_languages
        assert "java" in settings.supported_languages
        assert "go" in settings.supported_languages

    def test_file_extensions(self):
        settings = Settings(_env_file=None)
        assert ".py" in settings.file_extensions["python"]
        assert ".java" in settings.file_extensions["java"]
        assert ".go" in settings.file_extensions["go"]
        assert ".ts" in settings.file_extensions["typescript"]
        assert ".tsx" in settings.file_extensions["typescript"]
