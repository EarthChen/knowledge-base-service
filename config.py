"""Configuration for the knowledge base service."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, field_validator
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
    #: ``disabled`` — no LLM enrichment during indexing (default). ``core_only`` —
    #: enrich only high-value entities (see ``EnrichmentPriorityClassifier``).
    enrichment_strategy: str = "disabled"
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
    synthesis_max_tokens: int = 2000
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)

    @field_validator("enrichment_strategy")
    @classmethod
    def validate_enrichment_strategy(cls, v: str) -> str:
        allowed = frozenset({"disabled", "core_only"})
        if v not in allowed:
            msg = f"enrichment_strategy must be one of {sorted(allowed)}, got {v!r}"
            raise ValueError(msg)
        return v

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


class HybridSearchConfig(BaseModel):
    """Hybrid keyword + semantic + graph search defaults."""

    query_expansion_enabled: bool = True
    include_raw_docs_in_results: bool = False
    use_child_chunks: bool = True
    child_chunk_window_chars: int = 800
    child_chunk_stride_chars: int = 600
    child_chunk_min_parent_chars: int = 400
    enable_bm25: bool = True
    bm25_weight: float = 1.2


class RerankConfig(BaseModel):
    """Configuration for cross-encoder reranking."""

    enabled: bool = False
    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"
    batch_size: int = 32
    top_n: int = 30


class WikiConfig(BaseModel):
    """Application-level wiki feature flags (separate from ``wiki.models.WikiConfig``)."""

    cot_enabled: bool = False
    cot_analysis_model: str = ""
    cot_generation_model: str = ""
    auto_update_on_index: bool = False

    tree_enabled: bool = True
    dual_view_enabled: bool = True
    cross_reference_enabled: bool = True
    cross_reference_min_confidence: float = 0.5
    cross_repo_domain_enabled: bool = False
    knowledge_injection_enabled: bool = True

    git_publish_enabled: bool = False
    git_publish_mode: str = "incremental"
    git_publish_trigger: str = "manual"
    git_publish_schedule: str = "0 2 * * *"
    git_remote_url: str = ""
    git_branch: str = "main"
    git_author_name: str = "KBS Wiki Bot"
    git_author_email: str = "wiki-bot@company.com"
    git_token: str = ""
    export_default_view: str = "business_domain"
    export_min_tier: str = "standard"
    export_dir_naming: str = "original"

    coverage_report_enabled: bool = True
    stale_detection_enabled: bool = True
    suggested_questions_enabled: bool = True

    # Phase 1: Code-aware generation
    code_budget_enabled: bool = True
    core_code_budget: int = 20000
    standard_code_budget: int = 8000
    skeleton_code_budget: int = 1000
    importance_core_percentile: int = 80
    importance_standard_percentile: int = 30

    # Phase 2: RAG retrieval
    rag_enabled: bool = True
    rag_top_k: int = 5
    rag_min_score: float = 0.3
    rag_exclude_same_parent: bool = True
    chunk_embedding_batch_size: int = 64
    chunk_embedding_max_length: int = 512

    # Phase 3: Tiered generation + enrichment
    enrichment_enabled: bool = True
    enrichment_round1_enabled: bool = True
    enrichment_round2_enabled: bool = True
    # Phase 3: Business domain (classification only; pipeline integration in Phase 4)
    business_domain_enabled: bool = False
    business_domain_infrastructure_label: str = "__infrastructure__"
    # Phase 4: Cross-repo business-level wiki
    business_wiki_batch_threshold: int = 100

    mcp_server_enabled: bool = False

    lint_scheduler_enabled: bool = False
    lint_scheduler_interval_hours: int = 6
    feedback_enabled: bool = True
    auto_heal_enabled: bool = False

    deep_research_enabled: bool = False
    concept_merging_enabled: bool = False
    concept_merge_similarity_threshold: float = Field(default=0.9, ge=0.0, le=1.0)

    # Phase 2 SP3: confidence scoring
    confidence_scoring_enabled: bool = False
    confidence_weight_w1: float = 0.30
    confidence_weight_w2: float = 0.25
    confidence_weight_w3: float = 0.25
    confidence_weight_w4: float = 0.20
    confidence_weight_w5: float = 1.0

    # Phase 2 SP4: contradiction detection
    contradiction_detection_enabled: bool = False
    contradiction_similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # Phase 2 SP5: claim supersession history
    supersession_tracking_enabled: bool = False


class GitConfig(BaseModel):
    """Git repository management for remote indexing.

    When ``gitlab_url`` and ``gitlab_token`` are set, the index API
    accepts ``git_url`` and automatically clones/pulls the repository
    before indexing.  Supports HTTPS (token-injected) and SSH modes.
    """

    gitlab_url: str = ""
    gitlab_token: str = ""
    #: Optional token for ``POST /api/v1/pr/fetch`` when resolving GitHub PR URLs.
    github_token: str = ""
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
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    hybrid_search: HybridSearchConfig = Field(default_factory=HybridSearchConfig)
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

    rate_limit_rpm: int = 120
    rate_limit_trust_proxy: bool = False

    #: When ``True``, the service refuses to start without API tokens and
    #: protected routes return 403 if authentication is not configured.
    require_auth: bool = False

    api_token: str = ""
    api_tokens: str = ""
    tokens_file: str = "tokens.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
