"""Tests for knowledge base service configuration."""

from core.config import AppWikiFlags, EmbeddingConfig, FalkorDBConfig, Settings, get_settings


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
        assert cfg.model_name == "BAAI/bge-m3"
        assert cfg.dimension == 1024
        assert cfg.device == "auto"
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

    def test_wiki_sp7_flags_defaults(self) -> None:
        w = AppWikiFlags()
        assert w.forgetting_enabled is True
        assert w.schema_validation_enabled is True
        assert w.schema_path == "wiki/schema.yaml"
        assert w.forgetting_initial_stability == 7.0
        settings = Settings(_env_file=None)
        assert settings.wiki.schema_path == "wiki/schema.yaml"
        assert settings.wiki.forgetting_enabled is True
        assert settings.wiki.schema_validation_enabled is True


def test_wiki_skeleton_strategy_default() -> None:
    settings = get_settings()
    assert settings.wiki.skeleton_strategy == "template"
    assert settings.wiki.wikilink_cache_enabled is True


def test_wiki_incremental_enabled_default() -> None:
    w = AppWikiFlags()
    assert w.incremental_enabled is False
    settings = Settings(_env_file=None)
    assert settings.wiki.incremental_enabled is False


def test_heal_l2_threshold_default() -> None:
    """L2 heal threshold should default to 0.5 so L2 scores trigger healing."""
    w = AppWikiFlags()
    assert w.heal_l2_threshold == 0.5
    settings = Settings(_env_file=None)
    assert settings.wiki.heal_l2_threshold == 0.5
