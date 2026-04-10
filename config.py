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
    model_name: str = "BAAI/bge-m3"
    dimension: int = 1024
    device: str = "auto"
    backend: str = "onnx"
    onnx_path: str = ""
    batch_size: int = 32
    chunk_size: int = 64
    use_fp16: bool = True
    max_length: int = 8192
    query_prefix: str = ""
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

    def resolve_backend(self) -> str:
        """Resolve the best backend given current device and platform.

        On Mac with MPS available, prefer torch backend for GPU acceleration
        (ONNX Runtime does not support MPS; CoreML may be unavailable).
        """
        if self.backend != "auto":
            return self.backend

        device = self.resolve_device()
        if device == "mps":
            return "torch"
        return "onnx"


class LLMConfig(BaseModel):
    """Configuration for LLM provider (OpenAI-compatible protocol)."""

    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    deep_search_model: str = "gpt-4o"
    max_concurrent: int = 10
    timeout: int = 30
    retry_count: int = 3
    temperature: float = 0.1


class RerankConfig(BaseModel):
    """Configuration for cross-encoder reranking."""

    enabled: bool = False
    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"
    batch_size: int = 32
    top_n: int = 30


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
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)

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

    exclude_dirs: list[str] = Field(
        default_factory=lambda: [
            "node_modules", ".git", ".venv", "venv", "__pycache__",
            "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
            "vendor", "target",
            ".cursor", ".agent", ".agents", ".vscode", ".idea", ".fleet",
            ".windsurf", ".continue", ".aider", ".copilot",
        ]
    )

    api_token: str = ""
    api_tokens: str = ""
    tokens_file: str = "tokens.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
