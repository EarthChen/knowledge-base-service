"""Configuration for the knowledge base service."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

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


class GatewayConfig(BaseModel):
    """Configuration for ACP Gateway feedback-loop mode.

    When enabled, LLM enrichment and optionally deep search use
    the ACP Gateway's WebSocket + feedback mechanism, allowing
    task reuse across indexing operations (one task = one billing unit).

    ``ws_url`` and ``http_url`` are auto-derived from
    ``LLMConfig.base_url`` when left empty, so typically only
    ``enabled = true`` needs to be set.

    ``enrichment_enabled`` controls whether indexing generates LLM
    ``business_summary`` fields (gateway or direct). When false, indexing
    skips enrichment for faster runs; gateway may still be used for deep search.
    """

    enabled: bool = False
    enrichment_enabled: bool = True
    ws_url: str = ""
    http_url: str = ""
    idle_timeout: int = Field(default=3600, ge=60)


class LLMConfig(BaseModel):
    """Configuration for LLM provider (OpenAI-compatible protocol)."""

    enabled: bool = False
    # Optional indexing-time LLM passes (default off; see gateway.enrichment_enabled for
    # business_summary / CodeSummaryEnricher).
    concept_extraction_enabled: bool = False
    business_flow_enabled: bool = False
    default_provider: str = "gateway"
    fallback_provider: str = ""
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    deep_search_model: str = "gpt-4o"
    max_concurrent: int = 10
    timeout: int = 30
    retry_count: int = 3
    temperature: float = 0.1
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)

    def resolve_gateway_urls(self) -> tuple[str, str]:
        """Return ``(ws_url, http_url)`` for gateway connections.

        Auto-derives from ``base_url`` when the gateway fields are empty.
        E.g. ``http://localhost:9090/v1`` → ws ``ws://localhost:9090/acp/v1/connect``
        and http ``http://localhost:9090``.
        """
        gw = self.gateway

        if gw.http_url:
            http_url = gw.http_url.rstrip("/")
        else:
            http_url = self.base_url.rsplit("/v1", 1)[0].rstrip("/")

        if gw.ws_url:
            ws_url = gw.ws_url
        else:
            ws_url = f"ws{http_url.removeprefix('http')}/acp/v1/connect"

        return ws_url, http_url


class RerankConfig(BaseModel):
    """Configuration for cross-encoder reranking."""

    enabled: bool = False
    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"
    batch_size: int = 32
    top_n: int = 30


class GitConfig(BaseModel):
    """Git repository management for remote indexing.

    When ``gitlab_url`` and ``gitlab_token`` are set, the index API
    accepts ``git_url`` and automatically clones/pulls the repository
    before indexing.  Supports HTTPS (token-injected) and SSH modes.
    """

    gitlab_url: str = ""
    gitlab_token: str = ""
    ssh_key_path: str = ""
    clone_base_path: str = "./data/repos"
    clone_timeout: int = 600
    pull_timeout: int = 120
    ssl_verify: bool = False


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
    git: GitConfig = Field(default_factory=GitConfig)

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
