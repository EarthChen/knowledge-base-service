"""Configuration for the knowledge base service."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FalkorDBConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    graph_name: str = "code_knowledge"


class EmbeddingConfig(BaseModel):
    model_name: str = "nomic-ai/CodeRankEmbed"
    dimension: int = 768
    device: str = "auto"
    backend: str = "onnx"
    onnx_path: str = ""
    batch_size: int = 32
    chunk_size: int = 64
    use_fp16: bool = True
    max_length: int = 8192
    query_prefix: str = "Represent this query for searching relevant code: "
    trust_remote_code: bool = True

    def resolve_device(self) -> str:
        """Resolve ``"auto"`` to the best available accelerator.

        Priority: cuda > mps > cpu.
        """
        if self.device != "auto":
            return self.device

        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8100
    log_level: str = "INFO"

    falkordb_password: str = ""

    falkordb: FalkorDBConfig = Field(default_factory=FalkorDBConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

    supported_languages: list[str] = Field(
        default_factory=lambda: ["python", "java", "go", "javascript", "typescript"]
    )
    file_extensions: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "python": [".py"],
            "java": [".java"],
            "go": [".go"],
            "javascript": [".js", ".jsx", ".mjs"],
            "typescript": [".ts", ".tsx"],
        }
    )

    api_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
